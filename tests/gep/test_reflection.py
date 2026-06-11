"""Tests for evolver.gep.reflection."""

import time
from unittest.mock import patch

import pytest

from evolver.gep.reflection import (
    MAX_DELTA,
    ReflectionDelta,
    apply_delta,
    compute_delta,
    reflect,
    should_reflect,
    _score_recent_attempts,
)


class TestScoreRecentAttempts:
    def test_empty_events(self):
        sr, ac, an = _score_recent_attempts([])
        assert sr == 0.5
        assert ac == 0.5
        assert an == 0.5

    def test_success_rate(self):
        now = time.time()
        events = [
            {"type": "attempt", "timestamp": now, "outcome": "success", "changed_files": ["a.py"]},
            {"type": "attempt", "timestamp": now, "outcome": "failure", "changed_files": ["b.py"]},
        ]
        sr, ac, an = _score_recent_attempts(events, now=now)
        assert sr == 0.5

    def test_outside_window_ignored(self):
        now = time.time()
        events = [
            {"type": "attempt", "timestamp": now - 100000, "outcome": "success"},
        ]
        sr, ac, an = _score_recent_attempts(events, window_seconds=3600, now=now)
        assert sr == 0.5  # no recent attempts


class TestComputeDelta:
    def test_low_success(self):
        delta = compute_delta(0.3, 0.5, 0.5)
        assert delta.rigor > 0
        assert delta.risk_tolerance < 0
        assert abs(delta.rigor) <= MAX_DELTA

    def test_high_success(self):
        delta = compute_delta(0.9, 0.5, 0.5)
        assert delta.creativity > 0
        assert delta.risk_tolerance >= 0

    def test_high_complexity(self):
        delta = compute_delta(0.6, 0.8, 0.5)
        assert delta.rigor > 0
        assert delta.risk_tolerance < 0

    def test_low_novelty(self):
        delta = compute_delta(0.6, 0.3, 0.1)
        assert delta.creativity > 0

    def test_clamping(self):
        # Extreme values should still be clamped
        delta = compute_delta(0.0, 1.0, 0.0)
        assert abs(delta.rigor) <= MAX_DELTA
        assert abs(delta.risk_tolerance) <= MAX_DELTA
        assert abs(delta.creativity) <= MAX_DELTA


class TestApplyDelta:
    def test_applies_and_clamps(self, tmp_path):
        personality = {"rigor": 0.5, "creativity": 0.5, "risk_tolerance": 0.5}
        with patch("evolver.gep.reflection.load_personality", return_value=personality):
            with patch("evolver.gep.reflection.save_personality") as mock_save:
                result = apply_delta(ReflectionDelta(rigor=0.1, creativity=-0.1, risk_tolerance=0.3))
        assert result["rigor"] == pytest.approx(0.6, rel=0.01)
        assert result["creativity"] == pytest.approx(0.4, rel=0.01)
        assert result["risk_tolerance"] == pytest.approx(0.8, rel=0.01)
        mock_save.assert_called_once()

    def test_clamps_to_zero(self):
        personality = {"rigor": 0.05, "creativity": 0.05, "risk_tolerance": 0.05}
        with patch("evolver.gep.reflection.load_personality", return_value=personality):
            with patch("evolver.gep.reflection.save_personality"):
                result = apply_delta(ReflectionDelta(rigor=-0.2, creativity=-0.2, risk_tolerance=-0.2))
        assert result["rigor"] == 0.0
        assert result["creativity"] == 0.0
        assert result["risk_tolerance"] == 0.0


class TestReflect:
    def test_dry_run(self):
        now = time.time()
        events = [
            {"type": "attempt", "timestamp": now, "outcome": "success", "changed_files": ["a.py"]},
        ]
        with patch("evolver.gep.reflection.load_personality", return_value={"rigor": 0.5, "creativity": 0.5, "risk_tolerance": 0.5}):
            with patch("evolver.gep.reflection.save_personality") as mock_save:
                delta = reflect(events=events, dry_run=True, now=now)
        assert isinstance(delta, ReflectionDelta)
        mock_save.assert_not_called()

    def test_live_run(self):
        now = time.time()
        events = [
            {"type": "attempt", "timestamp": now, "outcome": "failure", "changed_files": ["a.py"]},
        ]
        with patch("evolver.gep.reflection.load_personality", return_value={"rigor": 0.5, "creativity": 0.5, "risk_tolerance": 0.5}):
            with patch("evolver.gep.reflection.save_personality") as mock_save:
                delta = reflect(events=events, dry_run=False, now=now)
        assert isinstance(delta, ReflectionDelta)
        mock_save.assert_called_once()


class TestShouldReflect:
    def test_no_last_reflection(self):
        assert should_reflect()

    def test_recent_reflection(self):
        now = time.time()
        assert not should_reflect(last_reflection_timestamp=now, now=now)

    def test_old_reflection(self):
        now = time.time()
        assert should_reflect(last_reflection_timestamp=now - 7200, now=now, min_elapsed_seconds=3600)


class TestReflectionDelta:
    def test_significant(self):
        assert ReflectionDelta(rigor=0.1).is_significant()

    def test_not_significant(self):
        assert not ReflectionDelta(rigor=0.01).is_significant()
