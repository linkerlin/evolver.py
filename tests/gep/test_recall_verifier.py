"""Tests for evolver.gep.recall_verifier."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from evolver.gep.recall_verifier import (
    STALE_THRESHOLD_SECONDS,
    VerificationResult,
    _compute_drift,
    _staleness,
    filter_valid_recalls,
    verify_all_recalls,
    verify_recall,
)


class TestStaleness:
    def test_fresh(self):
        assert _staleness(time.time() - 10, time.time()) == pytest.approx(10 / STALE_THRESHOLD_SECONDS, rel=0.01)

    def test_very_stale(self):
        assert _staleness(0, time.time()) == 1.0

    def test_exact_threshold(self):
        now = time.time()
        assert _staleness(now - STALE_THRESHOLD_SECONDS, now) == 1.0


class TestDrift:
    def test_no_files(self):
        event = {"changed_files": []}
        assert _compute_drift(event) == 0.0

    def test_unchanged_file(self, tmp_path):
        f = tmp_path / "foo.py"
        f.write_text("line1\nline2\n", encoding="utf-8")
        event = {"changed_files": ["foo.py"], "file_line_counts": {"foo.py": 2}}
        with patch("evolver.gep.recall_verifier.get_workspace_root", return_value=tmp_path):
            drift = _compute_drift(event)
        assert drift == 0.0

    def test_missing_file(self, tmp_path):
        event = {"changed_files": ["missing.py"], "file_line_counts": {"missing.py": 10}}
        with patch("evolver.gep.recall_verifier.get_workspace_root", return_value=tmp_path):
            drift = _compute_drift(event)
        assert drift == 1.0

    def test_different_line_count(self, tmp_path):
        f = tmp_path / "foo.py"
        f.write_text("line1\n", encoding="utf-8")
        event = {"changed_files": ["foo.py"], "file_line_counts": {"foo.py": 10}}
        with patch("evolver.gep.recall_verifier.get_workspace_root", return_value=tmp_path):
            drift = _compute_drift(event)
        assert 0 < drift <= 1.0


class TestVerifyRecall:
    def test_valid(self):
        event = {
            "event_id": "e1",
            "timestamp": time.time(),
            "changed_files": [],
            "outcome": "success",
        }
        result = verify_recall(event)
        assert isinstance(result, VerificationResult)
        assert result.valid
        assert result.reason == "ok"

    def test_stale(self):
        event = {
            "event_id": "e1",
            "timestamp": 0,
            "changed_files": [],
            "outcome": "success",
        }
        result = verify_recall(event)
        assert not result.valid
        assert "stale" in result.reason


class TestVerifyAllRecalls:
    def test_filters(self):
        events = [
            {"type": "attempt", "event_id": "e1", "timestamp": time.time(), "changed_files": []},
            {"type": "signal", "event_id": "e2", "timestamp": time.time()},
        ]
        results = verify_all_recalls(events=events)
        assert len(results) == 1
        assert results[0].recall_id == "e1"


class TestFilterValidRecalls:
    def test_keeps_valid(self):
        events = [
            {"type": "attempt", "event_id": "e1", "timestamp": time.time(), "changed_files": []},
        ]

        class FakeMatch:
            event_id = "e1"

        matches = [FakeMatch()]
        valid = filter_valid_recalls(matches, events=events)
        assert len(valid) == 1

    def test_drops_invalid(self):
        events = [
            {"type": "attempt", "event_id": "e1", "timestamp": 0, "changed_files": []},
        ]

        class FakeMatch:
            event_id = "e1"

        matches = [FakeMatch()]
        valid = filter_valid_recalls(matches, events=events)
        assert valid == []


import time
