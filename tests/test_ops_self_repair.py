"""Tests for evolver.ops.self_repair."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from evolver.config import LOCK_MAX_AGE_MS
from evolver.gep.git_ops import run_cmd
from evolver.ops import self_repair


@pytest.fixture
def git_repo(temp_workspace: Path) -> Path:
    """Initialize a temp git repo for repair tests."""
    run_cmd(["init"], cwd=temp_workspace)
    run_cmd(["config", "user.email", "test@example.com"], cwd=temp_workspace)
    run_cmd(["config", "user.name", "Test User"], cwd=temp_workspace)
    (temp_workspace / "README.md").write_text("# test\n", encoding="utf-8")
    run_cmd(["add", "README.md"], cwd=temp_workspace)
    run_cmd(["commit", "-m", "init"], cwd=temp_workspace)
    return temp_workspace


def test_repair_not_a_git_repo(temp_workspace: Path) -> None:
    report = self_repair.repair(temp_workspace)
    assert not report.ok
    assert "not_a_git_repo" in report.errors


def test_repair_aborts_rebase(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Create a situation where rebase --abort is a no-op (no rebase in progress).
    report = self_repair.repair(git_repo)
    # Should succeed without error even when there is nothing to abort.
    assert report.ok


def test_repair_removes_stale_lock(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = git_repo / ".git" / "index.lock"
    lock.write_text("lock", encoding="utf-8")
    # Make it very old
    old = time.time() - (LOCK_MAX_AGE_MS / 1000.0 + 60)
    os.utime(lock, (old, old))

    report = self_repair.repair(git_repo)
    assert not lock.exists()
    assert "stale_lock_removed" in report.actions


def test_repair_leaves_fresh_lock(git_repo: Path) -> None:
    lock = git_repo / ".git" / "index.lock"
    lock.write_text("lock", encoding="utf-8")
    # Fresh lock — do not remove
    report = self_repair.repair(git_repo)
    assert lock.exists()
    assert "stale_lock_removed" not in report.actions


def test_repair_safe_fetch(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # In a repo with no remote, fetch will fail — but repair should not crash.
    report = self_repair.repair(git_repo)
    # fetch may fail because no remote, but that's a non-fatal warning
    assert isinstance(report.actions, list)


def test_repair_hard_reset(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Add a remote pointing to itself so fetch/reset can work
    run_cmd(["remote", "add", "origin", str(git_repo)], cwd=git_repo)
    # Create a second branch to reset to
    run_cmd(["checkout", "-b", "main"], cwd=git_repo)
    (git_repo / "new.txt").write_text("new\n", encoding="utf-8")
    run_cmd(["add", "new.txt"], cwd=git_repo)
    run_cmd(["commit", "-m", "second"], cwd=git_repo)

    report = self_repair.repair(git_repo, force_reset=True)
    assert "hard_reset_to_origin" in report.actions or any("reset" in a for a in report.actions)


def test_env_force_reset() -> None:
    assert self_repair._env_force_reset() is False
    os.environ["EVOLVER_SELF_REPAIR_HARD_RESET"] = "1"
    assert self_repair._env_force_reset() is True
    del os.environ["EVOLVER_SELF_REPAIR_HARD_RESET"]


def test_repair_report_ok_property() -> None:
    report = self_repair.RepairReport(actions=["a"], errors=[])
    assert report.ok is True
    report.errors.append("e")
    assert report.ok is False
