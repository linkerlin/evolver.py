"""Single-instance lock for evolver daemon loop.

Equivalent to evolver/src/ops/instanceLock.js.
Prevents multiple evolver processes from running simultaneously.

Round-97 (DEBUG #52): mutual exclusion is the OS lock alone. flock/lockfile
handles vanish when the holder dies, so a leftover file is not a held lock
and a live holder can never be "stale". The old mtime heuristic stole locks
from daemons alive longer than five minutes and let two racing starters
delete each other into double instances (TOCTOU).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from filelock import FileLock, Timeout

from evolver.gep.paths import get_evolver_home

LOCK_FILENAME = "instance.lock"

#: The OS lock this process holds, or None. Release must only ever touch
#: the lock its own process acquired — the old release unlinked the path
#: unconditionally, deleting whatever lock file happened to be there.
_held_lock: FileLock | None = None


def _lock_path() -> Path:
    home = get_evolver_home()
    home.mkdir(parents=True, exist_ok=True)
    return home / LOCK_FILENAME


def acquire_instance_lock(
    *,
    blocking: bool = False,
    timeout: float = 0.0,
) -> bool:
    """Try to acquire the single-instance lock.

    Returns ``True`` if the lock was acquired, ``False`` otherwise. A
    leftover lock file from a crashed holder carries no OS lock and is
    reclaimed by the next acquire (the PID is simply overwritten); a live
    holder is unstealable at any age.
    """
    global _held_lock
    path = _lock_path()
    lock = FileLock(str(path))
    try:
        lock.acquire(blocking=blocking, timeout=timeout)
    except Timeout:
        return False
    _held_lock = lock
    # PID is diagnostics only — the OS lock is the exclusion
    with suppress(OSError):
        path.write_text(f"{os.getpid()}\n", encoding="utf-8")
    return True


def release_instance_lock() -> None:
    """Release the lock this process holds — and only that one.

    A release from a process that never acquired (or already released) is a
    no-op: it must not delete a lock file some other live process holds.
    """
    global _held_lock
    if _held_lock is None:
        return
    with suppress(RuntimeError, OSError):
        _held_lock.release()
    _held_lock = None
    with suppress(OSError):
        _lock_path().unlink(missing_ok=True)


@contextmanager
def instance_lock_ctx(
    *,
    blocking: bool = False,
    timeout: float = 0.0,
) -> Iterator[bool]:
    """Context manager for the single-instance lock.

    Yields ``True`` on successful acquisition, ``False`` otherwise.
    Releases the lock on context exit.
    """
    acquired = acquire_instance_lock(blocking=blocking, timeout=timeout)
    try:
        yield acquired
    finally:
        if acquired:
            release_instance_lock()


__all__ = [
    "LOCK_FILENAME",
    "acquire_instance_lock",
    "instance_lock_ctx",
    "release_instance_lock",
]
