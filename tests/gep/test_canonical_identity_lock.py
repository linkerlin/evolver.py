"""Tests for evolver.gep.canonical_identity_lock.

Ports Node's ``test/canonicalIdentityLock.test.js`` (8 contracts).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from evolver.gep import canonical_identity_lock as cil


@pytest.fixture(autouse=True)
def _reset_test_hooks() -> None:
    yield
    cil._set_before_abandoned_lock_unlink_for_testing(None)
    cil._set_process_start_identity_reader_for_testing(None)
    cil._reset_canonical_identity_lock_timing_for_testing()


def test_stale_remover_never_deletes_live_successor_after_owner_aba(tmp_path: Path) -> None:
    root = tmp_path
    node_id_file = root / "node_id"
    lock_dir = Path(f"{node_id_file}.tuple.lock")
    owner_file = lock_dir / "owner.stale-owner.json"
    acquired_file = root / "p2-acquired"
    release_file = root / "release-p2"
    released_file = root / "p2-released"

    lock_dir.mkdir(parents=True, exist_ok=True)
    owner_file.write_text(
        json.dumps({"pid": 999_999_999, "token": "stale-owner"}),
        encoding="utf-8",
    )

    child_script = f"""
import time
from pathlib import Path
from evolver.gep.canonical_identity_lock import acquire_canonical_identity_lock
node = {str(node_id_file)!r}
acquired = Path({str(acquired_file)!r})
release = Path({str(release_file)!r})
released = Path({str(released_file)!r})
rel = acquire_canonical_identity_lock(node)
acquired.write_text("1", encoding="utf-8")
deadline = time.time() + 10
while not release.exists() and time.time() < deadline:
    time.sleep(0.01)
if not release.exists():
    raise SystemExit("release signal timeout")
rel()
released.write_text("1", encoding="utf-8")
"""

    child: subprocess.Popen[bytes] | None = None
    try:
        cil._set_canonical_identity_lock_timing_for_testing({"waitMs": 1, "timeoutMs": 75})

        def on_before_unlink(_info: dict) -> None:
            nonlocal child
            cil._set_before_abandoned_lock_unlink_for_testing(None)
            child = subprocess.Popen(
                [sys.executable, "-c", child_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deadline = time.time() + 5
            while not acquired_file.exists() and time.time() < deadline:
                time.sleep(0.01)
            assert acquired_file.exists(), "P2 must acquire the replacement lock"

        cil._set_before_abandoned_lock_unlink_for_testing(on_before_unlink)

        with pytest.raises(cil.CanonicalIdentityLockError) as exc_info:
            cil.acquire_canonical_identity_lock(node_id_file)
        assert exc_info.value.code == "CANONICAL_IDENTITY_LOCK_TIMEOUT"
        assert child is not None, "the interleaving must start P2"
        assert lock_dir.exists(), "P2 lock must remain present after P1 resumes"

        release_file.write_text("1", encoding="utf-8")
        assert child.wait(timeout=10) == 0
        deadline = time.time() + 5
        while not released_file.exists() and time.time() < deadline:
            time.sleep(0.01)
        assert released_file.exists()
        assert not lock_dir.exists(), "P2 release must remove its own lock cleanly"
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_acquire_recovers_aged_empty_lock_directory(tmp_path: Path) -> None:
    node_id_file = tmp_path / "node_id"
    lock_dir = Path(f"{node_id_file}.tuple.lock")
    lock_dir.mkdir(parents=True, exist_ok=True)
    stale_at = time.time() - 120
    os.utime(lock_dir, (stale_at, stale_at))

    release = cil.acquire_canonical_identity_lock(node_id_file)
    assert lock_dir.exists()
    release()
    assert not lock_dir.exists()


def test_acquire_recovers_aged_truncated_token_owner(tmp_path: Path) -> None:
    node_id_file = tmp_path / "node_id"
    lock_dir = Path(f"{node_id_file}.tuple.lock")
    owner_file = lock_dir / "owner.truncated-token.json"
    lock_dir.mkdir(parents=True, exist_ok=True)
    owner_file.write_text('{"pid":', encoding="utf-8")
    stale_at = time.time() - 120
    os.utime(lock_dir, (stale_at, stale_at))

    release = cil.acquire_canonical_identity_lock(node_id_file)
    names = os.listdir(lock_dir)
    assert len(names) == 1
    assert re.match(r"^owner\.[a-zA-Z0-9-]+\.json$", names[0])
    assert names[0] != owner_file.name
    release()
    assert not lock_dir.exists()


def test_partial_owner_preparation_failure_never_exposes_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    node_id_file = tmp_path / "node_id"
    lock_dir = Path(f"{node_id_file}.tuple.lock")
    real_open = os.open
    injected = {"done": False}

    def inject_partial_open(
        path: str | bytes | os.PathLike[str], flags: int, mode: int = 0o777, *a, **kw
    ):  # type: ignore[no-untyped-def]
        path_s = str(path)
        if (
            not injected["done"]
            and ".tuple.lock.owner." in path_s
            and path_s.endswith(".tmp")
            and (flags & os.O_CREAT)
        ):
            injected["done"] = True
            # Create a partial file then fail like ENOSPC after truncated write.
            fd = real_open(path, flags, mode, *a, **kw)
            os.write(fd, b'{"pid":')
            os.close(fd)
            err = OSError("injected partial owner write failure")
            err.errno = 28  # ENOSPC
            err.strerror = "No space left on device"
            raise err
        return real_open(path, flags, mode, *a, **kw)

    monkeypatch.setattr(os, "open", inject_partial_open)

    with pytest.raises(OSError) as exc_info:
        cil.acquire_canonical_identity_lock(node_id_file)
    assert getattr(exc_info.value, "errno", None) == 28 or "injected" in str(exc_info.value)
    assert not lock_dir.exists(), "partial owner must never be published"
    leftovers = [n for n in os.listdir(tmp_path) if ".tuple.lock.owner." in n]
    assert leftovers == [], "partial staging files must be removed"

    monkeypatch.setattr(os, "open", real_open)
    release = cil.acquire_canonical_identity_lock(node_id_file)
    release()


def test_release_cleanup_failure_leaves_path_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    node_id_file = tmp_path / "node_id"
    lock_dir = Path(f"{node_id_file}.tuple.lock")
    release = cil.acquire_canonical_identity_lock(node_id_file)

    real_rmdir = os.rmdir
    injected = {"done": False}

    def inject_rmdir(path: str | bytes | os.PathLike[str]) -> None:
        path_s = str(path)
        if not injected["done"] and path_s.startswith(f"{lock_dir}.release."):
            injected["done"] = True
            err = OSError("injected interrupted release cleanup")
            err.errno = 4  # EINTR
            raise err
        return real_rmdir(path)

    monkeypatch.setattr(os, "rmdir", inject_rmdir)
    # Path.rmdir also uses os.rmdir underneath on CPython.
    with pytest.raises(OSError) as exc_info:
        release()
    assert "injected" in str(exc_info.value) or getattr(exc_info.value, "errno", None) == 4
    assert not lock_dir.exists(), "release residue must not occupy canonical path"

    monkeypatch.setattr(os, "rmdir", real_rmdir)
    successor = cil.acquire_canonical_identity_lock(node_id_file)
    successor()
    assert not lock_dir.exists()


def test_legacy_fixed_owner_marker_fails_closed(tmp_path: Path) -> None:
    node_id_file = tmp_path / "node_id"
    lock_dir = Path(f"{node_id_file}.tuple.lock")
    owner_file = lock_dir / "owner.json"
    lock_dir.mkdir(parents=True, exist_ok=True)
    owner_file.write_text(
        json.dumps({"pid": 999_999_999, "token": "legacy-stale-owner"}),
        encoding="utf-8",
    )
    stale_at = time.time() - 120
    os.utime(lock_dir, (stale_at, stale_at))
    cil._set_canonical_identity_lock_timing_for_testing({"waitMs": 1, "timeoutMs": 20})

    with pytest.raises(cil.CanonicalIdentityLockError) as exc_info:
        cil.acquire_canonical_identity_lock(node_id_file)
    assert exc_info.value.code == "CANONICAL_IDENTITY_LOCK_TIMEOUT"
    assert owner_file.exists()


def test_reclaims_lock_when_pid_has_different_start_identity(tmp_path: Path) -> None:
    node_id_file = tmp_path / "node_id"
    lock_dir = Path(f"{node_id_file}.tuple.lock")
    owner_file = lock_dir / "owner.reused-pid.json"
    lock_dir.mkdir(parents=True, exist_ok=True)
    owner_file.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "token": "reused-pid",
                "processStartIdentity": "previous-process-start",
            }
        ),
        encoding="utf-8",
    )
    cil._set_process_start_identity_reader_for_testing(lambda _pid: "current-process-start")

    release = cil.acquire_canonical_identity_lock(node_id_file)
    assert not owner_file.exists(), "the prior process lock must be reclaimed"
    release()
    assert not lock_dir.exists()


def test_never_reclaims_same_process_identity_even_when_old(tmp_path: Path) -> None:
    node_id_file = tmp_path / "node_id"
    lock_dir = Path(f"{node_id_file}.tuple.lock")
    owner_file = lock_dir / "owner.same-process.json"
    lock_dir.mkdir(parents=True, exist_ok=True)
    owner_file.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "token": "same-process",
                "processStartIdentity": "current-process-start",
            }
        ),
        encoding="utf-8",
    )
    stale_at = time.time() - 120
    os.utime(lock_dir, (stale_at, stale_at))
    cil._set_process_start_identity_reader_for_testing(lambda _pid: "current-process-start")
    cil._set_canonical_identity_lock_timing_for_testing({"waitMs": 1, "timeoutMs": 20})

    with pytest.raises(cil.CanonicalIdentityLockError) as exc_info:
        cil.acquire_canonical_identity_lock(node_id_file)
    assert exc_info.value.code == "CANONICAL_IDENTITY_LOCK_TIMEOUT"
    assert owner_file.exists(), "the live owner marker must remain intact"
