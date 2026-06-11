"""Issue reporter — automatically create GitHub Issues for recurring failures.

Equivalent to Node's ``evolver/src/gep/issueReporter.js``.

Monitors the memory graph for repeated failures on the same signal.
When a signal fails 3+ times, an Issue is drafted and (if
``GITHUB_TOKEN`` is available) submitted to the repository's GitHub
Issues.

Deduplication
-------------
1. Local cache (`evolver/.config/issue_cache.json`) stores recently
   reported signal keys with timestamps.
2. GitHub API search for open issues with the same signal key.
3. Cool-down: 7 days before the same signal can be reported again.

Sanitisation
------------
* Usernames in paths → ``<USER>``
* Tokens / secrets → ``<REDACTED>``
* Home directory prefix → ``~``

Design notes
------------
* Silent when ``GITHUB_TOKEN`` is missing — no errors.
* All network calls use ``httpx`` with 10s timeout.
* Atomic writes for local cache.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from evolver.gep.epigenetics import capture_env_fingerprint, env_fingerprint_key
from evolver.gep.paths import get_workspace_root
from evolver.gep.sanitize import full_leak_check

logger = logging.getLogger(__name__)

# Thresholds
FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 7 * 86400  # 7 days

# Cache file
ISSUE_CACHE_PATH = Path("evolver") / ".config" / "issue_cache.json"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class IssueDraft:
    title: str
    body: str
    signal_key: str
    labels: list[str] = field(default_factory=lambda: ["evolver-auto", "bug"])


# ---------------------------------------------------------------------------
# Sanitisation
# ---------------------------------------------------------------------------


def _sanitise(text: str) -> str:
    """Sanitise *text* for public issue posting."""
    # Redact tokens
    text = re.sub(r"(?i)(bearer\s+)[a-z0-9_\-\.]{10,}", r"\1<REDACTED>", text)
    text = re.sub(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s]+", r"\1<REDACTED>", text)
    text = re.sub(r"(?i)(token\s*[:=]\s*)[^\s]+", r"\1<REDACTED>", text)
    # Redact home directory
    home = os.path.expanduser("~")
    text = text.replace(home, "~")
    # Redact username in paths
    text = re.sub(r"/users/[^/]+/", "/users/<USER>/", text, flags=re.IGNORECASE)
    text = re.sub(r"/home/[^/]+/", "/home/<USER>/", text)
    text = re.sub(r"c:\\users\\[^\\]+\\", r"C:\\Users\\<USER>\\", text, flags=re.IGNORECASE)
    return text


# ---------------------------------------------------------------------------
# Failure counting
# ---------------------------------------------------------------------------


def _count_failures_by_signal(
    events: list[dict[str, Any]] | None,
    window_seconds: float = COOLDOWN_SECONDS,
    now: float | None = None,
) -> dict[str, int]:
    """Return a mapping ``signal_key -> failure_count`` for recent events."""
    if events is None:
        events = []
    t = now if now is not None else time.time()
    cutoff = t - window_seconds
    counts: dict[str, int] = {}
    for ev in events:
        if ev.get("type") != "attempt":
            continue
        ts = ev.get("timestamp", 0)
        if ts < cutoff:
            continue
        outcome = str(ev.get("outcome", "")).lower()
        if "success" in outcome or "pass" in outcome:
            continue
        # Build a stable signal key
        signals = ev.get("signals_snapshot") or ev.get("signals", [])
        key = hashlib.sha256(
            json.dumps(signals, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16]
        counts[key] = counts.get(key, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _load_cache(path: Path | None = None) -> dict[str, float]:
    p = path or (get_workspace_root() / ISSUE_CACHE_PATH)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return {k: float(v) for k, v in data.items()}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _save_cache(cache: dict[str, float], path: Path | None = None) -> None:
    p = path or (get_workspace_root() / ISSUE_CACHE_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(p)


# ---------------------------------------------------------------------------
# Drafting
# ---------------------------------------------------------------------------


def _draft_issue(signal_key: str, events: list[dict[str, Any]]) -> IssueDraft | None:
    """Create an :class:`IssueDraft` for *signal_key*."""
    # Find the most recent event with this signal key
    representative: dict[str, Any] | None = None
    for ev in reversed(events):
        signals = ev.get("signals_snapshot") or ev.get("signals", [])
        key = hashlib.sha256(
            json.dumps(signals, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16]
        if key == signal_key:
            representative = ev
            break

    if not representative:
        return None

    signals = representative.get("signals_snapshot") or representative.get("signals", [])
    signal_text = " | ".join(signals[:3]) if signals else "unknown"
    env = env_fingerprint_key(capture_env_fingerprint())
    gene_id = representative.get("gene_id", "unknown")
    outcome = representative.get("outcome", "unknown")
    error = representative.get("error", "")

    title = f"[evolver-auto] Recurring failure: {signal_text}"
    body_lines = [
        "## Auto-Generated Issue",
        "",
        f"**Signal**: `{signal_text}`",
        f"**Gene ID**: `{gene_id}`",
        f"**Outcome**: `{outcome}`",
        f"**Env Fingerprint**: `{env}`",
        "",
        "### Error",
        "",
        f"```\n{_sanitise(error)}\n```" if error else "_No error message captured._",
        "",
        "---",
        "",
        "_This issue was automatically generated by evolver. "
        "If the signal is resolved, this issue can be safely closed._",
    ]
    return IssueDraft(
        title=title,
        body="\n".join(body_lines),
        signal_key=signal_key,
    )


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------


def _github_token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def _repo_from_git() -> str | None:
    """Try to extract ``owner/repo`` from the local git remote."""
    try:
        import subprocess

        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(get_workspace_root()),
        )
        if result.returncode != 0:
            return None
        url = result.stdout.strip()
        # ssh: git@github.com:owner/repo.git
        # https: https://github.com/owner/repo.git
        m = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", url)
        if m:
            return m.group(1)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.debug("[IssueReporter] Failed to detect repo from git remote: %s", exc)
    return None


def _search_existing_issues(repo: str, signal_key: str, token: str) -> bool:
    """Return ``True`` if an open issue for *signal_key* already exists."""
    try:
        import httpx

        query = f"repo:{repo} is:issue is:open {signal_key} in:body"
        resp = httpx.get(
            "https://api.github.com/search/issues",
            params={"q": query, "per_page": 1},
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            return int(data.get("total_count", 0)) > 0
    except Exception as exc:
        logger.debug("[IssueReporter] GitHub search failed: %s", exc)
    return False


def _create_issue(repo: str, draft: IssueDraft, token: str) -> dict[str, Any] | None:
    """Create a GitHub issue. Returns the API response or ``None``."""
    try:
        import httpx

        resp = httpx.post(
            f"https://api.github.com/repos/{repo}/issues",
            json={
                "title": draft.title,
                "body": draft.body,
                "labels": draft.labels,
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=10.0,
        )
        if resp.status_code in (200, 201):
            return cast(dict[str, Any], resp.json())
        logger.warning(
            "[IssueReporter] GitHub API returned %d: %s", resp.status_code, resp.text[:200]
        )
    except Exception as exc:
        logger.warning("[IssueReporter] Failed to create issue: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def report_recurring_failures(
    *,
    events: list[dict[str, Any]] | None = None,
    cache_path: Path | None = None,
) -> list[str]:
    """Scan for recurring failures and report them as GitHub Issues.

    Returns a list of created issue URLs (or empty list if none created).
    """
    token = _github_token()
    repo = _repo_from_git()
    cache = _load_cache(cache_path)
    now = time.time()

    # Prune old cache entries
    cache = {k: v for k, v in cache.items() if (now - v) < COOLDOWN_SECONDS}

    created: list[str] = []
    counts = _count_failures_by_signal(events)

    for signal_key, count in counts.items():
        if count < FAILURE_THRESHOLD:
            continue
        if signal_key in cache:
            continue

        draft = _draft_issue(signal_key, events or [])
        if draft is None:
            continue

        # Leak check the draft
        leak = full_leak_check(draft.body)
        if not leak["safe"]:
            logger.warning("[IssueReporter] Draft contains potential secrets — skipping")
            continue

        if not token or not repo:
            logger.info("[IssueReporter] Would create issue for %s (no token/repo)", signal_key)
            cache[signal_key] = now
            continue

        if _search_existing_issues(repo, signal_key, token):
            logger.info("[IssueReporter] Issue already exists for %s", signal_key)
            cache[signal_key] = now
            continue

        result = _create_issue(repo, draft, token)
        if result:
            url = result.get("html_url", "")
            logger.info("[IssueReporter] Created issue: %s", url)
            created.append(url)
            cache[signal_key] = now

    _save_cache(cache, cache_path)
    return created


def should_report(signal_key: str, *, cache_path: Path | None = None) -> bool:
    """Return ``True`` if *signal_key* is not in cooldown."""
    cache = _load_cache(cache_path)
    now = time.time()
    if signal_key in cache:
        return (now - cache[signal_key]) >= COOLDOWN_SECONDS
    return True
