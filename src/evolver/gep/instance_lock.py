"""Single-instance lock for evolver daemon loop.

Equivalent to evolver/src/ops/instanceLock.js.
Prevents multiple evolver processes from running simultaneously.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

from evolver.gep.paths import get_evolver_home

LOCK_FILENAME = "instance.lock"
LOCK_MAX_AGE_SEC = 300  # 5 minutes — stale lock threshold


def _lock_path() -> Path:
    home = get_evolver_home()
    home.mkdir(parents=True, exist_ok=True)
    return home / LOCK_FILENAME


def _is_lock_stale(path: Path, max_age_sec: float = LOCK_MAX_AGE_SEC) -> bool:
    if not path.exists():
        return True
    try:
        mtime = path.stat().st_mtime
        return (time.time() - mtime) > max_age_sec
    except OSError:
        return True


def acquire_instance_lock(
    *,
    blocking: bool = False,
    timeout: float = 0.0,
    max_age_sec: float = LOCK_MAX_AGE_SEC,
) -> bool:
    """Try to acquire the single-instance lock.

    Returns ``True`` if the lock was acquired, ``False`` otherwise.
    If the existing lock is stale (older than *max_age_sec*), it is
    broken and re-acquired.
    """
    path = _lock_path()
    lock = FileLock(str(path))

    if _is_lock_stale(path, max_age_sec):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    try:
        lock.acquire(blocking=blocking, timeout=timeout)
        # Update mtime so other processes see it as fresh
        try:
            os.utime(path, None)
        except OSError:
            pass
        return True
    except Timeout:
        return False


def release_instance_lock() -> None:
    """Release the single-instance lock if held by this process."""
    path = _lock_path()
    lock = FileLock(str(path))
    try:
        lock.release()
    except (RuntimeError, OSError):
        pass
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


@contextmanager
def instance_lock_ctx(
    *,
    blocking: bool = False,
    timeout: float = 0.0,
    max_age_sec: float = LOCK_MAX_AGE_SEC,
) -> Iterator[bool]:
    """Context manager for the single-instance lock.

    Yields ``True`` on successful acquisition, ``False`` otherwise.
    Releases the lock on context exit.
    """
    acquired = acquire_instance_lock(blocking=blocking, timeout=timeout, max_age_sec=max_age_sec)
    try:
        yield acquired
    finally:
        if acquired:
            release_instance_lock()
