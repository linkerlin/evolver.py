"""Tests for evolver.gep.curriculum."""

from unittest.mock import patch

from evolver.gep.curriculum import (
    CurriculumState,
    CurriculumTask,
    add_task,
    advance_level,
    ingest_exploration_tasks,
    load_state,
    next_tasks,
    record_attempt,
    save_state,
)


class TestCurriculumTask:
    def test_success_rate(self):
        t = CurriculumTask("t1", "desc", difficulty=2, attempts=4, successes=3)
        assert t.success_rate == 0.75

    def test_success_rate_zero_attempts(self):
        t = CurriculumTask("t1", "desc")
        assert t.success_rate == 0.0

    def test_round_trip_dict(self):
        t = CurriculumTask("t1", "desc", difficulty=3, priority=0.8)
        d = t.to_dict()
        t2 = CurriculumTask.from_dict(d)
        assert t2.task_id == t.task_id
        assert t2.difficulty == t.difficulty
        assert t2.priority == t.priority


class TestPersistence:
    def test_save_and_load(self, tmp_path):
        with patch(
            "evolver.gep.curriculum._curriculum_path", return_value=tmp_path / "curriculum.json"
        ):
            state = CurriculumState(current_level=2)
            state.tasks.append(CurriculumTask("t1", "desc"))
            save_state(state)
            loaded = load_state()
            assert loaded.current_level == 2
            assert len(loaded.tasks) == 1
            assert loaded.tasks[0].task_id == "t1"

    def test_load_missing(self, tmp_path):
        with patch(
            "evolver.gep.curriculum._curriculum_path", return_value=tmp_path / "missing.json"
        ):
            state = load_state()
            assert state.current_level == 1
            assert state.tasks == []


class TestTaskManagement:
    def test_add_task(self, tmp_path):
        with patch(
            "evolver.gep.curriculum._curriculum_path", return_value=tmp_path / "curriculum.json"
        ):
            t = add_task("t1", "description", difficulty=2, priority=0.9)
            assert t.task_id == "t1"
            assert t.difficulty == 2
            state = load_state()
            assert any(task.task_id == "t1" for task in state.tasks)

    def test_add_replaces_existing(self, tmp_path):
        with patch(
            "evolver.gep.curriculum._curriculum_path", return_value=tmp_path / "curriculum.json"
        ):
            add_task("t1", "old", difficulty=1)
            add_task("t1", "new", difficulty=3)
            state = load_state()
            assert len([t for t in state.tasks if t.task_id == "t1"]) == 1
            assert state.tasks[0].difficulty == 3

    def test_record_attempt(self, tmp_path):
        with patch(
            "evolver.gep.curriculum._curriculum_path", return_value=tmp_path / "curriculum.json"
        ):
            add_task("t1", "desc")
            t = record_attempt("t1", success=True)
            assert t is not None
            assert t.attempts == 1
            assert t.successes == 1

    def test_record_attempt_missing(self, tmp_path):
        with patch(
            "evolver.gep.curriculum._curriculum_path", return_value=tmp_path / "curriculum.json"
        ):
            assert record_attempt("missing", success=True) is None

    def test_mastery_completes(self, tmp_path):
        with patch(
            "evolver.gep.curriculum._curriculum_path", return_value=tmp_path / "curriculum.json"
        ):
            add_task("t1", "desc")
            for _ in range(3):
                record_attempt("t1", success=True)
            state = load_state()
            assert state.tasks[0].completed


class TestAdvanceLevel:
    def test_advances_when_empty(self, tmp_path):
        with patch(
            "evolver.gep.curriculum._curriculum_path", return_value=tmp_path / "curriculum.json"
        ):
            level = advance_level()
            assert level == 2

    def test_does_not_advance_with_pending(self, tmp_path):
        with patch(
            "evolver.gep.curriculum._curriculum_path", return_value=tmp_path / "curriculum.json"
        ):
            add_task("t1", "desc", difficulty=1)
            level = advance_level()
            assert level == 1


class TestNextTasks:
    def test_returns_tasks_at_level(self, tmp_path):
        with patch(
            "evolver.gep.curriculum._curriculum_path", return_value=tmp_path / "curriculum.json"
        ):
            with patch("evolver.gep.curriculum.is_enabled", return_value=True):
                add_task("t1", "desc", difficulty=2)
                add_task("t2", "desc2", difficulty=2)
                tasks = next_tasks(count=2, level=2)
                assert len(tasks) == 2
                assert all(t.difficulty == 2 for t in tasks)

    def test_respects_feature_flag(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_CURRICULUM", "0")
        with patch(
            "evolver.gep.curriculum._curriculum_path", return_value=tmp_path / "curriculum.json"
        ):
            assert next_tasks(count=3) == []


class TestIngestExploration:
    def test_ingests_signals(self, tmp_path):
        with patch(
            "evolver.gep.curriculum._curriculum_path", return_value=tmp_path / "curriculum.json"
        ):
            signals = [
                {
                    "file_path": "/a.py",
                    "line": 10,
                    "task_type": "todo",
                    "description": "fix",
                    "priority": 0.8,
                },
            ]
            count = ingest_exploration_tasks(signals)
            assert count == 1
            state = load_state()
            assert any("explore" in t.source for t in state.tasks)

    def test_deduplicates(self, tmp_path):
        with patch(
            "evolver.gep.curriculum._curriculum_path", return_value=tmp_path / "curriculum.json"
        ):
            signals = [
                {
                    "file_path": "/a.py",
                    "line": 10,
                    "task_type": "todo",
                    "description": "fix",
                    "priority": 0.8,
                },
            ]
            ingest_exploration_tasks(signals)
            count = ingest_exploration_tasks(signals)
            assert count == 0
