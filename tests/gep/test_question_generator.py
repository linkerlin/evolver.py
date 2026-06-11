"""Tests for evolver.gep.question_generator."""

import time

from evolver.gep.question_generator import (
    DAILY_LIMIT,
    _compute_bounty,
    _is_infrastructure_error,
    _load_state,
    _reset_daily_counter,
    _save_state,
    _signal_priority,
    generate_questions,
)


class TestInfrastructureError:
    def test_network(self):
        assert _is_infrastructure_error({"error": "Connection timeout"})

    def test_disk(self):
        assert _is_infrastructure_error({"error": "disk full"})

    def test_not_infra(self):
        assert not _is_infrastructure_error({"error": "test failed"})


class TestSignalPriority:
    def test_critical(self):
        assert _signal_priority({"severity": "critical"}) == "critical"

    def test_high(self):
        assert _signal_priority({"tags": ["high"]}) == "high"

    def test_default(self):
        assert _signal_priority({}) == "low"


class TestComputeBounty:
    def test_critical(self):
        assert _compute_bounty("critical", 1) >= 50

    def test_repeated(self):
        b1 = _compute_bounty("medium", 1)
        b5 = _compute_bounty("medium", 5)
        assert b5 > b1


class TestState:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "state.json"
        state = {"daily_count": 2, "last_reset": time.time(), "questions": []}
        _save_state(state, path=path)
        loaded = _load_state(path=path)
        assert loaded["daily_count"] == 2

    def test_reset_counter(self):
        old = time.time() - 2 * 86400
        state = {"daily_count": 3, "last_reset": old, "questions": []}
        state = _reset_daily_counter(state)
        assert state["daily_count"] == 0

    def test_no_reset_same_day(self):
        now = time.time()
        state = {"daily_count": 3, "last_reset": now, "questions": []}
        state = _reset_daily_counter(state)
        assert state["daily_count"] == 3


class TestGenerateQuestions:
    def test_no_failures(self):
        questions = generate_questions(events=[], max_questions=3)
        assert questions == []

    def test_below_daily_limit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_QUESTION_GENERATOR", "1")
        events = [
            {
                "type": "attempt",
                "timestamp": time.time(),
                "outcome": "failure",
                "signals": ["auth"],
                "error": "bug",
            },
            {
                "type": "attempt",
                "timestamp": time.time(),
                "outcome": "failure",
                "signals": ["auth"],
                "error": "bug",
            },
        ]
        questions = generate_questions(
            events=events, max_questions=3, state_path=tmp_path / "state.json"
        )
        assert len(questions) >= 1
        assert questions[0].priority == "low"

    def test_infrastructure_filtered(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_QUESTION_GENERATOR", "1")
        events = [
            {
                "type": "attempt",
                "timestamp": time.time(),
                "outcome": "failure",
                "signals": ["net"],
                "error": "timeout",
            },
            {
                "type": "attempt",
                "timestamp": time.time(),
                "outcome": "failure",
                "signals": ["net"],
                "error": "timeout",
            },
        ]
        questions = generate_questions(
            events=events, max_questions=3, state_path=tmp_path / "state.json"
        )
        assert questions == []

    def test_daily_limit(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_QUESTION_GENERATOR", "1")
        state = {"daily_count": DAILY_LIMIT, "last_reset": time.time(), "questions": []}
        _save_state(state, path=tmp_path / "state.json")
        events = [
            {
                "type": "attempt",
                "timestamp": time.time(),
                "outcome": "failure",
                "signals": ["auth"],
                "error": "bug",
            },
            {
                "type": "attempt",
                "timestamp": time.time(),
                "outcome": "failure",
                "signals": ["auth"],
                "error": "bug",
            },
        ]
        questions = generate_questions(
            events=events, max_questions=DAILY_LIMIT, state_path=tmp_path / "state.json"
        )
        assert questions == []

    def test_feature_flag_off(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_FF_ENABLE_QUESTION_GENERATOR", "0")
        assert generate_questions(events=[]) == []
