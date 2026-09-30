"""Tests for evolver.gep.instance_lock.

Round-97 (DEBUG #52) semantics: the OS lock is the only truth. A leftover
file is not a held lock (reclaimed), a live holder is unstealable at any age,
and release only ever deletes the lock its own process acquired.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from evolver.gep import instance_lock as il


@pytest.fixture
def isolated_lock_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path))
    yield tmp_path
    # A failed test can leave the module state holding a lock from an older
    # tmp dir; drop it so later tests start clean (each test has its own home).
    il._held_lock = None


def test_acquire_and_release(isolated_lock_dir: Path) -> None:
    assert il.acquire_instance_lock(blocking=False, timeout=0) is True
    # While held, the lock file exists (Windows holds an exclusive handle —
    # the file's CONTENT is not readable back even in-process, so existence
    # is the observable contract here).
    assert il._lock_path().exists()
    il.release_instance_lock()
    assert not il._lock_path().exists()


def test_reacquire_after_release(isolated_lock_dir: Path) -> None:
    assert il.acquire_instance_lock(blocking=False, timeout=0) is True
    il.release_instance_lock()
    assert il.acquire_instance_lock(blocking=False, timeout=0) is True
    il.release_instance_lock()


def test_context_manager(isolated_lock_dir: Path) -> None:
    with il.instance_lock_ctx(blocking=False, timeout=0) as acquired:
        assert acquired is True
    assert not il._lock_path().exists()


def test_a_leftover_file_from_a_crashed_holder_is_reclaimed(
    isolated_lock_dir: Path,
) -> None:
    """No holder = no OS lock = free to take, however old the file looks."""
    lock_path = il._lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("12345\n")
    old = time.time() - 400
    os.utime(lock_path, (old, old))
    assert il.acquire_instance_lock(blocking=False, timeout=0) is True
    il.release_instance_lock()


def test_release_without_acquire_never_deletes_a_foreign_lock(
    isolated_lock_dir: Path,
) -> None:
    """The old release unlinked the path unconditionally — a stray release
    from a process that never held the lock deleted a live foreign one."""
    lock_path = il._lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("4242\n")
    il.release_instance_lock()  # no-op by contract
    assert lock_path.exists()

    il.release_instance_lock()  # still no-op
    assert lock_path.read_text(encoding="utf-8").strip() == "4242"


def test_a_live_holder_is_never_stolen(isolated_lock_dir: Path) -> None:
    """A subprocess holds the OS lock; even an ancient-looking lock file
    must not let this process steal it. Old mtime heuristic did."""
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import time\n"
            "from evolver.gep.instance_lock import acquire_instance_lock\n"
            "acquire_instance_lock()\n"
            "print('held', flush=True)\n"
            "time.sleep(60)\n",
        ],
        env={**os.environ, "EVOLVER_HOME": str(isolated_lock_dir)},
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        # Age the file far past the historical 300s threshold: a live holder
        # must still be unstealable.
        old = time.time() - 4000
        os.utime(il._lock_path(), (old, old))
        assert il.acquire_instance_lock(blocking=False, timeout=0) is False
    finally:
        holder.kill()
        holder.wait()

    # Holder dead: the OS lock vanished with it; the leftover file is free.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if il.acquire_instance_lock(blocking=False, timeout=0):
            il.release_instance_lock()
            return
        time.sleep(0.2)
    pytest.fail("lock not reclaimable after the holder died")
