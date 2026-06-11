"""Tests for evolver.gep.task_receiver."""

import time
from unittest.mock import patch

import pytest

from evolver.gep.task_receiver import (
    ExternalTask,
    MAX_CONCURRENT_EXTERNAL,
    _capability_match,
    _load_claimed_tasks,
    _save_task,
    get_active_tasks,
    warn_upcoming_deadlines,
)


class TestCapabilityMatch:
    def test_exact_match(self):
        genes = [{"signal_keywords": ["auth", "login"], "intent": "auth"}]
        score = _capability_match(["auth", "login"], genes)
        assert score > 0.5

    def test_no_match(self):
        genes = [{"signal_keywords": ["auth"]}]
        score = _capability_match(["database"], genes)
        assert score == 0.0

    def test_empty(self):
        assert _capability_match([], []) == 0.0


class TestTaskLog:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "tasks.jsonl"
        task = ExternalTask("t1", "bugfix", 10.0, time.time() + 3600, ["auth"])
        _save_task(task, path=path)
        loaded = _load_claimed_tasks(path=path)
        assert len(loaded) == 1
        assert loaded[0].task_id == "t1"


class TestExternalTask:
    def test_roi(self):
        t = ExternalTask("t1", "bugfix", 10.0, time.time(), [], estimated_hours=2.0)
        assert t.roi() == 5.0

    def test_roi_zero_hours(self):
        t = ExternalTask("t1", "bugfix", 10.0, time.time(), [], estimated_hours=0.0)
        assert t.roi() == float("inf")


class TestGetActiveTasks:
    def test_filters(self, tmp_path):
        path = tmp_path / "tasks.jsonl"
        active = ExternalTask("t1", "bugfix", 10.0, time.time() + 3600, [])
        active.status = "in_progress"
        completed = ExternalTask("t2", "bugfix", 10.0, time.time() + 3600, [])
        completed.status = "completed"
        _save_task(active, path=path)
        _save_task(completed, path=path)
        result = get_active_tasks(path=path)
        assert len(result) == 1
        assert result[0].task_id == "t1"


class TestWarnDeadlines:
    def test_warns_urgent(self, tmp_path):
        path = tmp_path / "tasks.jsonl"
        task = ExternalTask("t1", "bugfix", 10.0, time.time() + 1800, [])
        task.status = "in_progress"
        _save_task(task, path=path)
        urgent = warn_upcoming_deadlines(warning_seconds=3600, path=path)
        assert len(urgent) == 1

    def test_no_warn_far(self, tmp_path):
        path = tmp_path / "tasks.jsonl"
        task = ExternalTask("t1", "bugfix", 10.0, time.time() + 86400, [])
        task.status = "in_progress"
        _save_task(task, path=path)
        urgent = warn_upcoming_deadlines(warning_seconds=3600, path=path)
        assert len(urgent) == 0
