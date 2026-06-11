"""Open PR registry — track pending PRs to avoid duplicate submissions.

Equivalent to Node's ``evolver/src/gep/openPRRegistry.js``.

Persists metadata about PRs created by :mod:`self_pr` so that:
1. The same gene/gene-id isn't re-submitted within the cool-down period.
2. Merged/closed PRs can be detected and archived.
3. Diff-dedup has a corpus to compare against.

Storage
-------
``evolver/.config/open_pr_registry.json`` — atomic writes (tmp + replace).

Schema
------
```json
{
  "version": 1,
  "prs": [
    {
      "pr_number": 42,
      "pr_url": "https://github.com/.../pull/42",
      "branch": "evolver-auto/...",
      "gene_id": "abc123",
      "diff_hash": "sha256:...",
      "confidence": 0.92,
      "status": "open|merged|closed",
      "created_at": 1234567890,
      "updated_at": 1234567890
    }
  ]
}
```

Design notes
------------
* All timestamps are ``time.time()`` POSIX seconds.
* ``diff_hash`` is SHA-256 of the full diff text (first 16 hex chars).
* Thread-safe via module-level lock.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, cast

from evolver.gep.paths import get_workspace_root

logger = logging.getLogger(__name__)

REGISTRY_PATH = Path("evolver") / ".config" / "open_pr_registry.json"
_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _registry_path() -> Path:
    return get_workspace_root() / REGISTRY_PATH


def load_registry(path: Path | None = None) -> dict[str, Any]:
    """Load the PR registry from disk. Returns at least ``{"version": 1, "prs": []}``."""
    p = path or _registry_path()
    if not p.exists():
        return {"version": 1, "prs": []}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 1, "prs": []}
        data.setdefault("version", 1)
        data.setdefault("prs", [])
        return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[OpenPRRegistry] Failed to load registry: %s", exc)
        return {"version": 1, "prs": []}


def save_registry(data: dict[str, Any], path: Path | None = None) -> None:
    """Persist the registry atomically."""
    p = path or _registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(p)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def register_pr(
    pr_number: int,
    pr_url: str,
    branch: str,
    gene_id: str,
    diff_text: str,
    confidence: float,
    status: str = "open",
    path: Path | None = None,
) -> dict[str, Any]:
    """Register a newly created PR."""
    diff_hash = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()[:16]
    now = time.time()
    entry = {
        "pr_number": pr_number,
        "pr_url": pr_url,
        "branch": branch,
        "gene_id": gene_id,
        "diff_hash": diff_hash,
        "confidence": confidence,
        "status": status,
        "created_at": now,
        "updated_at": now,
    }
    with _lock:
        data = load_registry(path)
        data["prs"].append(entry)
        save_registry(data, path)
    logger.info("[OpenPRRegistry] Registered PR #%d (%s)", pr_number, pr_url)
    return entry


def update_pr_status(
    pr_number: int,
    status: str,
    path: Path | None = None,
) -> dict[str, Any] | None:
    """Update the status of a tracked PR."""
    with _lock:
        data = load_registry(path)
        for pr in data["prs"]:
            if pr.get("pr_number") == pr_number:
                pr["status"] = status
                pr["updated_at"] = time.time()
                save_registry(data, path)
                return cast(dict[str, Any], pr)
    return None


def get_open_prs(path: Path | None = None) -> list[dict[str, Any]]:
    """Return all PRs with ``status == 'open'``."""
    data = load_registry(path)
    return [pr for pr in data.get("prs", []) if pr.get("status") == "open"]


def archive_merged_prs(path: Path | None = None) -> list[dict[str, Any]]:
    """Mark open PRs as ``merged`` or ``closed`` based on remote state.

    This is a best-effort function. It tries to query GitHub via ``gh``
    CLI or GitHub API. PRs that cannot be verified are left as ``open``.

    Returns the list of PRs whose status changed.
    """
    import os
    import subprocess

    changed: list[dict[str, Any]] = []
    data = load_registry(path)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

    for pr in data.get("prs", []):
        if pr.get("status") != "open":
            continue
        pr_number = pr.get("pr_number")
        if not pr_number:
            continue

        # Try gh CLI first
        remote_status: str | None = None
        try:
            result = subprocess.run(
                ["gh", "pr", "view", str(pr_number), "--json", "state", "-q", ".state"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(get_workspace_root()),
            )
            if result.returncode == 0:
                remote_status = result.stdout.strip().lower()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Fallback to API
        if remote_status is None and token:
            try:
                import httpx

                # Extract repo from pr_url
                url = pr.get("pr_url", "")
                m = __import__("re").search(r"github\.com/([^/]+/[^/]+)/pull/", url)
                if m:
                    repo = m.group(1)
                    resp = httpx.get(
                        f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=10.0,
                    )
                    if resp.status_code == 200:
                        remote_status = resp.json().get("state", "").lower()
                        if resp.json().get("merged"):
                            remote_status = "merged"
            except Exception:
                pass

        if remote_status in ("merged", "closed"):
            update_pr_status(pr_number, remote_status, path)
            changed.append(pr)
            logger.info("[OpenPRRegistry] PR #%d archived as %s", pr_number, remote_status)

    return changed


def prune_old_entries(
    max_age_days: float = 30.0,
    path: Path | None = None,
) -> int:
    """Remove entries older than *max_age_days*. Returns number removed."""
    cutoff = time.time() - (max_age_days * 86400)
    with _lock:
        data = load_registry(path)
        original_len = len(data.get("prs", []))
        data["prs"] = [pr for pr in data["prs"] if pr.get("updated_at", 0) > cutoff]
        removed = original_len - len(data["prs"])
        if removed:
            save_registry(data, path)
            logger.info("[OpenPRRegistry] Pruned %d old entries", removed)
    return removed
