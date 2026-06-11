"""Tests for evolver.gep.task_receiver."""

import time
from unittest.mock import patch

from evolver.gep.task_receiver import (
    ExternalTask,
    _capability_match,
    _load_claimed_tasks,
    _poll_open_tasks,
    _save_task,
    get_active_tasks,
    receive_tasks,
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


class TestReceiveTasks:
    def test_claims_high_value_task(self, tmp_path, monkeypatch):
        path = tmp_path / "tasks.jsonl"
        monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")

        open_task = {
            "task_id": "hub-1",
            "task_type": "bugfix",
            "bounty": 100.0,
            "deadline": time.time() + 86400,
            "signals": ["auth", "login"],
            "estimated_hours": 2.0,
        }

        with (
            patch("evolver.gep.task_receiver.is_enabled", return_value=True),
            patch("evolver.gep.task_receiver._poll_open_tasks", return_value=[open_task]),
            patch("evolver.gep.task_receiver._claim_task", return_value=True),
        ):
            local_genes = [{"signal_keywords": ["auth", "login"], "intent": "auth"}]
            claimed = receive_tasks(local_genes=local_genes, max_concurrent=3, path=path)

        assert len(claimed) == 1
        assert claimed[0].task_id == "hub-1"
        assert claimed[0].roi() == 50.0

    def test_skips_low_match_task(self, tmp_path, monkeypatch):
        path = tmp_path / "tasks.jsonl"
        monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")

        open_task = {
            "task_id": "hub-2",
            "task_type": "ml",
            "bounty": 100.0,
            "deadline": time.time() + 86400,
            "signals": ["neural", "network"],
            "estimated_hours": 2.0,
        }

        with (
            patch("evolver.gep.task_receiver.is_enabled", return_value=True),
            patch("evolver.gep.task_receiver._poll_open_tasks", return_value=[open_task]),
            patch("evolver.gep.task_receiver._claim_task") as mock_claim,
        ):
            local_genes = [{"signal_keywords": ["auth"], "intent": "auth"}]
            claimed = receive_tasks(local_genes=local_genes, max_concurrent=3, path=path)

        assert len(claimed) == 0
        mock_claim.assert_not_called()

    def test_respects_concurrent_limit(self, tmp_path, monkeypatch):
        path = tmp_path / "tasks.jsonl"
        monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")

        # Pre-populate with 3 active tasks
        for i in range(3):
            t = ExternalTask(f"pre-{i}", "bugfix", 10.0, time.time() + 86400, [])
            _save_task(t, path=path)

        with patch("evolver.gep.task_receiver.is_enabled", return_value=True):
            claimed = receive_tasks(local_genes=[], max_concurrent=3, path=path)

        assert len(claimed) == 0

    def test_respects_cooldown(self, tmp_path, monkeypatch):
        path = tmp_path / "tasks.jsonl"
        monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")

        # Pre-populate with a recently claimed task of same type
        recent = ExternalTask("pre-1", "bugfix", 10.0, time.time() + 86400, ["auth"])
        recent.claimed_at = time.time() - 3600  # 1 hour ago (< 24h cooldown)
        _save_task(recent, path=path)

        open_task = {
            "task_id": "hub-3",
            "task_type": "bugfix",
            "bounty": 100.0,
            "deadline": time.time() + 86400,
            "signals": ["auth"],
            "estimated_hours": 2.0,
        }

        with (
            patch("evolver.gep.task_receiver.is_enabled", return_value=True),
            patch("evolver.gep.task_receiver._poll_open_tasks", return_value=[open_task]),
            patch("evolver.gep.task_receiver._claim_task") as mock_claim,
        ):
            local_genes = [{"signal_keywords": ["auth"], "intent": "auth"}]
            claimed = receive_tasks(local_genes=local_genes, max_concurrent=3, path=path)

        assert len(claimed) == 0
        mock_claim.assert_not_called()

    def test_skips_deadline_too_close(self, tmp_path, monkeypatch):
        path = tmp_path / "tasks.jsonl"
        monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")

        open_task = {
            "task_id": "hub-4",
            "task_type": "bugfix",
            "bounty": 100.0,
            "deadline": time.time() + 600,  # 10 minutes (< 1h warning)
            "signals": ["auth"],
            "estimated_hours": 2.0,
        }

        with (
            patch("evolver.gep.task_receiver.is_enabled", return_value=True),
            patch("evolver.gep.task_receiver._poll_open_tasks", return_value=[open_task]),
            patch("evolver.gep.task_receiver._claim_task") as mock_claim,
        ):
            local_genes = [{"signal_keywords": ["auth"], "intent": "auth"}]
            claimed = receive_tasks(local_genes=local_genes, max_concurrent=3, path=path)

        assert len(claimed) == 0
        mock_claim.assert_not_called()

    def test_disabled_returns_empty(self, tmp_path, monkeypatch):
        path = tmp_path / "tasks.jsonl"
        monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")

        with patch("evolver.gep.task_receiver.is_enabled", return_value=False):
            claimed = receive_tasks(local_genes=[], max_concurrent=3, path=path)

        assert claimed == []


class TestPollOpenTasks:
    def test_disabled_returns_empty(self):
        with patch("evolver.gep.task_receiver.is_enabled", return_value=False):
            assert _poll_open_tasks() == []
