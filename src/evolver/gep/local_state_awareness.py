"""Local state awareness — capture full project snapshot for GEP.

Equivalent to Node's ``evolver/src/gep/localStateAwareness.js``.

Collects a structured snapshot of the local project state:
git status, uncommitted changes, dirty files, environment,
and recent activity. Produces a stable hash + a human-readable
summary that can be injected into the GEP prompt.

Design notes
------------
* Uses ``subprocess.run`` for git commands, with ``cwd`` set to the
  workspace root so that any git repository on disk works.
* Hash is SHA-256 over the canonical JSON of the snapshot.
* Summary is a compact Markdown block (≈ 20 lines max).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evolver.gep.paths import get_workspace_root

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class LocalStateSnapshot:
    git_branch: str
    git_commit: str
    dirty_files: list[str]
    untracked_files: list[str]
    staged_files: list[str]
    env_vars: dict[str, str]
    recent_signals: list[dict[str, Any]]
    state_hash: str
    summary: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_git(*args: str, cwd: Path | None = None) -> str:
    """Run a git command and return stdout, or empty string on failure."""
    root = cwd or get_workspace_root()
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.debug("[LocalState] git command failed: %s", exc)
    return ""


def _capture_git_branch(root: Path) -> str:
    return _run_git("branch", "--show-current", cwd=root) or "unknown"


def _capture_git_commit(root: Path) -> str:
    return _run_git("rev-parse", "HEAD", cwd=root) or "unknown"


def _capture_git_status(root: Path) -> dict[str, list[str]]:
    """Return {dirty, untracked, staged} file lists from git status."""
    out = _run_git("status", "--porcelain", cwd=root)
    dirty: list[str] = []
    untracked: list[str] = []
    staged: list[str] = []
    for line in out.splitlines():
        if len(line) < 3:
            continue
        xy = line[:2]
        path_str = line[3:].strip()
        if xy == "??":
            untracked.append(path_str)
        elif xy[0] != " ":
            staged.append(path_str)
        elif xy[1] != " ":
            dirty.append(path_str)
    return {"dirty": dirty, "untracked": untracked, "staged": staged}


def _capture_env_vars() -> dict[str, str]:
    """Capture a curated subset of environment variables."""
    keys = [
        "EVOLVER_MODE",
        "EVOLVER_AGENT_ID",
        "EVOLVER_PROXY_URL",
        "EVOLVER_TASK_TYPE",
        "EVOLVER_ROLLBACK_MODE",
        "HOME",
        "USER",
        "PYTHONPATH",
    ]
    return {k: os.environ.get(k, "") for k in keys}


def _capture_recent_signals(limit: int = 5) -> list[dict[str, Any]]:
    """Read the most recent signals from the memory graph event stream."""
    try:
        from evolver.gep.memory_graph import MEMORY_EVENTS_PATH
        if not MEMORY_EVENTS_PATH.exists():
            return []
        events: list[dict[str, Any]] = []
        with open(MEMORY_EVENTS_PATH, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        events.append(obj)
                except json.JSONDecodeError:
                    continue
        # Return last *limit* signal-type events
        signals = [e for e in events if e.get("type") in ("signal", "mutation", "attempt")]
        return signals[-limit:]
    except Exception as exc:
        logger.debug("[LocalState] Failed to read recent signals: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def capture_snapshot() -> LocalStateSnapshot:
    """Capture the full local state snapshot."""
    root = get_workspace_root()
    branch = _capture_git_branch(root)
    commit = _capture_git_commit(root)
    status = _capture_git_status(root)
    env_vars = _capture_env_vars()
    recent_signals = _capture_recent_signals()

    summary_lines = [
        f"## Local State Summary",
        f"",
        f"- **Branch**: `{branch}`",
        f"- **Commit**: `{commit[:8]}`",
        f"- **Dirty**: {len(status['dirty'])} file(s)",
        f"- **Staged**: {len(status['staged'])} file(s)",
        f"- **Untracked**: {len(status['untracked'])} file(s)",
        f"",
    ]

    if status["dirty"]:
        summary_lines.append("**Dirty files:**")
        for f in status["dirty"][:10]:
            summary_lines.append(f"- `{f}`")
        if len(status["dirty"]) > 10:
            summary_lines.append(f"- ... and {len(status['dirty']) - 10} more")
        summary_lines.append("")

    if recent_signals:
        summary_lines.append("**Recent signals:**")
        for sig in recent_signals:
            sig_type = sig.get("type", "unknown")
            timestamp = sig.get("timestamp", "")
            summary_lines.append(f"- `{sig_type}` @ {timestamp}")
        summary_lines.append("")

    summary = "\n".join(summary_lines)

    canonical = json.dumps(
        {
            "branch": branch,
            "commit": commit,
            "dirty": sorted(status["dirty"]),
            "untracked": sorted(status["untracked"]),
            "staged": sorted(status["staged"]),
            "env_vars": {k: env_vars[k] for k in sorted(env_vars)},
            "recent_signals": recent_signals,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    state_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    return LocalStateSnapshot(
        git_branch=branch,
        git_commit=commit,
        dirty_files=status["dirty"],
        untracked_files=status["untracked"],
        staged_files=status["staged"],
        env_vars=env_vars,
        recent_signals=recent_signals,
        state_hash=state_hash,
        summary=summary,
    )


def get_state_summary() -> str:
    """Return a compact Markdown summary of the current local state."""
    return capture_snapshot().summary


def get_state_hash() -> str:
    """Return a short stable hash of the current local state."""
    return capture_snapshot().state_hash
