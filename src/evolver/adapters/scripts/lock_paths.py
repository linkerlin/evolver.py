"""Single source of truth for the daemon singleton-lock location and lease tunables.

Equivalent to ``evolver/src/adapters/scripts/_lockPaths.js`` (74 lines).

Shared by the daemon (``ops/lifecycle.py``) and the session-start hook's
auto-restart guard, so the lock resolution can never diverge between them
(issue #176).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Round-9 lease tunables. A live daemon refreshes the lock mtime every
# LOCK_REFRESH_S; a lock whose mtime is older than STALE_LOCK_TTL_S (written
# by a lease-aware daemon) is treated as stale even if its PID is alive —
# closing the "crash + PID reuse" and "SIGKILL leaves stale lock" holes.
# Windows TTL is shorter because TerminateProcess() (SIGTERM on win32)
# prevents the daemon's release_lock() from running.
_IS_WINDOWS = sys.platform == "win32"
STALE_LOCK_TTL_S: float = 3 * 60 if _IS_WINDOWS else 5 * 60
LOCK_REFRESH_S: float = 1 * 60 if _IS_WINDOWS else 2 * 60


def get_lock_file_path(env: dict[str, str] | None = None) -> Path:
    """Return the daemon singleton-lock path.

    ``EVOLVER_LOCK_DIR`` overrides for tests/sandboxed runs (basename
    ``evolver.pid``); otherwise defaults to ``~/.evomap/instance.lock``
    (per-user state dir so all install modes converge).
    """
    e = env if env is not None else os.environ
    if e.get("EVOLVER_LOCK_DIR"):
        return Path(e["EVOLVER_LOCK_DIR"]) / "evolver.pid"
    return Path.home() / ".evomap" / "instance.lock"


def lock_is_stale_by_lease(
    lock_file: Path,
    payload: dict[str, object] | None,
) -> bool:
    """Return True if a lease-aware lock's mtime is older than the stale TTL.

    Locks written by pre-lease daemons (``payload.lease is not True``) are
    never judged stale by mtime, so we never falsely steal an older daemon's
    lock.
    """
    if not payload or payload.get("lease") is not True:
        return False
    try:
        age_s = time.time() - lock_file.stat().st_mtime
        return age_s > STALE_LOCK_TTL_S
    except OSError:
        return False


__all__ = [
    "LOCK_REFRESH_S",
    "STALE_LOCK_TTL_S",
    "get_lock_file_path",
    "lock_is_stale_by_lease",
]
