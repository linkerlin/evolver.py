"""Tests for evolver.gep.local_state_awareness."""

import json
from unittest.mock import patch

import pytest

from evolver.gep.local_state_awareness import (
    LocalStateSnapshot,
    capture_snapshot,
    get_state_hash,
    get_state_summary,
)


class TestCaptureSnapshot:
    def test_returns_snapshot(self, tmp_path):
        with patch("evolver.gep.local_state_awareness.get_workspace_root", return_value=tmp_path):
            snap = capture_snapshot()
        assert isinstance(snap, LocalStateSnapshot)
        assert isinstance(snap.state_hash, str)
        assert len(snap.state_hash) == 16

    def test_git_branch_capture(self, tmp_path):
        with patch("evolver.gep.local_state_awareness.get_workspace_root", return_value=tmp_path):
            with patch("evolver.gep.local_state_awareness._run_git", return_value="main"):
                snap = capture_snapshot()
        assert snap.git_branch == "main"

    def test_git_commit_capture(self, tmp_path):
        with patch("evolver.gep.local_state_awareness.get_workspace_root", return_value=tmp_path):
            with patch("evolver.gep.local_state_awareness._run_git", side_effect=["main", "abc123" * 8, ""]):
                snap = capture_snapshot()
        assert snap.git_commit == "abc123" * 8

    def test_empty_repo(self, tmp_path):
        with patch("evolver.gep.local_state_awareness.get_workspace_root", return_value=tmp_path):
            with patch("evolver.gep.local_state_awareness._run_git", return_value=""):
                snap = capture_snapshot()
        assert snap.git_branch == "unknown"
        assert snap.git_commit == "unknown"

    def test_dirty_files_parsed(self, tmp_path):
        status_output = " M dirty.py\nA  staged.py\n?? untracked.py"
        with patch("evolver.gep.local_state_awareness.get_workspace_root", return_value=tmp_path):
            with patch("evolver.gep.local_state_awareness._run_git", side_effect=[
                "main",
                "abc123",
                status_output,
            ]):
                snap = capture_snapshot()
        assert "dirty.py" in snap.dirty_files
        assert "staged.py" in snap.staged_files
        assert "untracked.py" in snap.untracked_files

    def test_hash_stability(self, tmp_path):
        with patch("evolver.gep.local_state_awareness.get_workspace_root", return_value=tmp_path):
            with patch("evolver.gep.local_state_awareness._run_git", return_value="main"):
                snap1 = capture_snapshot()
                snap2 = capture_snapshot()
        assert snap1.state_hash == snap2.state_hash

    def test_summary_contains_branch(self, tmp_path):
        with patch("evolver.gep.local_state_awareness.get_workspace_root", return_value=tmp_path):
            with patch("evolver.gep.local_state_awareness._run_git", return_value="feature-x"):
                snap = capture_snapshot()
        assert "feature-x" in snap.summary


class TestGetStateHash:
    def test_returns_string(self, tmp_path):
        with patch("evolver.gep.local_state_awareness.get_workspace_root", return_value=tmp_path):
            with patch("evolver.gep.local_state_awareness._run_git", return_value="main"):
                h = get_state_hash()
        assert isinstance(h, str)
        assert len(h) == 16


class TestGetStateSummary:
    def test_returns_markdown(self, tmp_path):
        with patch("evolver.gep.local_state_awareness.get_workspace_root", return_value=tmp_path):
            with patch("evolver.gep.local_state_awareness._run_git", return_value="main"):
                summary = get_state_summary()
        assert "## Local State Summary" in summary
