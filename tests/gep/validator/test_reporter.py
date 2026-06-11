"""Tests for evolver.gep.validator.reporter."""

from pathlib import Path
from unittest.mock import patch

from evolver.gep.validator.reporter import (
    _append_to_queue,
    _load_queue,
    _rewrite_queue,
    flush_queue,
    submit_report,
)


class TestQueue:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "queue.jsonl"
        report = {"task_id": "t1", "status": "passed"}
        _append_to_queue(report, path=path)
        _rewrite_queue([report, {"task_id": "t2"}], path=path)
        loaded = _load_queue(path=path)
        assert len(loaded) == 2
        assert loaded[0]["task_id"] == "t1"

    def test_empty(self, tmp_path):
        assert _load_queue(path=tmp_path / "missing.jsonl") == []


class TestSubmitReport:
    def test_queues_on_failure(self, tmp_path):
        with patch("evolver.gep.validator.reporter._submit_single", return_value=False):
            result = submit_report({"task_id": "t1", "status": "passed"})
        assert not result

    def test_succeeds(self, tmp_path):
        with patch("evolver.gep.validator.reporter._submit_single", return_value=True):
            result = submit_report({"task_id": "t1", "status": "passed"})
        assert result


class TestFlushQueue:
    def test_empty(self):
        submitted, remaining = flush_queue(max_batch_size=10, path=Path("/nonexistent/queue.jsonl"))
        assert submitted == 0
        assert remaining == 0

    def test_flush_success(self, tmp_path):
        path = tmp_path / "queue.jsonl"
        entries = [
            {"task_id": "t1", "status": "passed", "_retries": 0, "_last_attempt": 0},
        ]
        _rewrite_queue(entries, path=path)
        with patch("evolver.gep.validator.reporter._submit_single", return_value=True):
            submitted, remaining = flush_queue(max_batch_size=10, path=path)
        assert submitted == 1
        assert remaining == 0

    def test_flush_failure(self, tmp_path):
        path = tmp_path / "queue.jsonl"
        entries = [
            {"task_id": "t1", "status": "passed", "_retries": 0, "_last_attempt": 0},
        ]
        _rewrite_queue(entries, path=path)
        with patch("evolver.gep.validator.reporter._submit_single", return_value=False):
            submitted, remaining = flush_queue(max_batch_size=10, path=path)
        assert submitted == 0
        assert remaining == 1

    def test_max_retries_drops(self, tmp_path):
        path = tmp_path / "queue.jsonl"
        entries = [
            {"task_id": "t1", "status": "passed", "_retries": 10, "_last_attempt": 0},
        ]
        _rewrite_queue(entries, path=path)
        submitted, remaining = flush_queue(max_batch_size=10, path=path)
        assert submitted == 0
        assert remaining == 0
