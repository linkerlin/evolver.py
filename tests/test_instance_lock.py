"""Tests for evolver.gep.instance_lock."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep import instance_lock as il


@pytest.fixture
def isolated_lock_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path))
    yield tmp_path


def test_acquire_and_release(isolated_lock_dir: Path) -> None:
    assert il.acquire_instance_lock(blocking=False, timeout=0) is True
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


def test_stale_lock_broken(isolated_lock_dir: Path) -> None:
    lock_path = il._lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("stale")
    import os
    import time

    old = time.time() - 400
    os.utime(lock_path, (old, old))
    assert il.acquire_instance_lock(blocking=False, timeout=0) is True
    il.release_instance_lock()
