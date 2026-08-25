"""Sprint 24.12: personality v2 — five axes, bucket stats, nudge, pivot."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep.personality import (
    AXES_V2,
    HISTORY_CAP,
    MIN_SAMPLES_FOR_BEST,
    MUTATE_DELTA_CLAMP,
    MUTATE_MAX_AXES,
    PERSONALITY_V2_DEFAULTS,
    adapt_personality,
    best_bucket,
    bucket_key,
    bucket_score,
    force_pivot,
    load_personality_v2,
    mutate_personality_v2,
    natural_nudge,
    record_axis_outcome,
)


class TestFiveAxes:
    def test_v2_defaults(self) -> None:
        assert AXES_V2 == (
            "rigor",
            "creativity",
            "verbosity",
            "risk_tolerance",
            "obedience",
        )
        state = load_personality_v2()
        for axis, default in PERSONALITY_V2_DEFAULTS.items():
            assert state[axis] == default

    def test_persisted_values_win(self, temp_workspace: Path) -> None:
        from evolver.gep.personality import save_personality

        save_personality({"rigor": 0.9})
        state = load_personality_v2()
        assert state["rigor"] == 0.9
        # Missing axes fall back to v2 defaults.
        assert state["obedience"] == PERSONALITY_V2_DEFAULTS["obedience"]


class TestBucketStats:
    def test_bucket_key_snaps_to_grid(self) -> None:
        assert bucket_key(0.77) == 0.8
        assert bucket_key(0.0) == 0.0
        assert bucket_key(1.0) == 1.0
        assert bucket_key(-3.0) == 0.0  # clamped

    def test_record_and_score(self, temp_workspace: Path) -> None:
        for score in (1.0, 0.9, 0.8):
            record_axis_outcome("rigor", 0.7, score)
        scored = bucket_score("rigor", 0.7)
        assert scored is not None
        blend, total = scored
        assert total == 3
        expected = 0.75 * (3 + 1) / (3 + 2) + 0.25 * (0.9 * min(1.0, 3 / 8))
        assert blend == pytest.approx(expected, abs=1e-4)

    def test_best_bucket_requires_samples(self, temp_workspace: Path) -> None:
        record_axis_outcome("rigor", 0.7, 1.0)
        assert best_bucket("rigor") is None  # below MIN_SAMPLES_FOR_BEST
        for _ in range(MIN_SAMPLES_FOR_BEST):
            record_axis_outcome("rigor", 0.7, 1.0)
        assert best_bucket("rigor") == 0.7

    def test_history_capped(self, temp_workspace: Path) -> None:
        for i in range(HISTORY_CAP + 20):
            record_axis_outcome("rigor", 0.5, float(i % 2))
        from evolver.gep.personality import _load_axis_stats

        assert len(_load_axis_stats()["rigor"]["history"]) == HISTORY_CAP


class TestNudgeAndMutate:
    def test_nudge_moves_toward_best_bucket(self, temp_workspace: Path) -> None:
        for _ in range(MIN_SAMPLES_FOR_BEST + 1):
            record_axis_outcome("creativity", 0.6, 1.0)
        nudged = natural_nudge({**PERSONALITY_V2_DEFAULTS, "creativity": 0.35})
        assert nudged["creativity"] == pytest.approx(0.45)  # +clip 0.1 toward 0.6

    def test_nudge_no_evidence_no_move(self, temp_workspace: Path) -> None:
        before = PERSONALITY_V2_DEFAULTS.copy()
        assert natural_nudge(before) == before

    def test_mutate_clamps_delta(self, temp_workspace: Path) -> None:
        mutated = mutate_personality_v2(
            dict(PERSONALITY_V2_DEFAULTS),
            {"rigor": 0.9},  # exceeds clamp
        )
        assert mutated["rigor"] == pytest.approx(
            PERSONALITY_V2_DEFAULTS["rigor"] + MUTATE_DELTA_CLAMP
        )

    def test_mutate_axis_budget(self, temp_workspace: Path) -> None:
        deltas = dict.fromkeys(AXES_V2, -0.1)
        mutated = mutate_personality_v2(dict(PERSONALITY_V2_DEFAULTS), deltas)
        changed = sum(
            1 for axis in AXES_V2 if mutated[axis] != pytest.approx(PERSONALITY_V2_DEFAULTS[axis])
        )
        assert changed == MUTATE_MAX_AXES


class TestForcePivot:
    def test_required_stronger_than_suggested(self) -> None:
        base = {"creativity": 0.3, "risk_tolerance": 0.3}
        suggested = force_pivot(base)
        required = force_pivot(base, strength="required")
        assert required["creativity"] > suggested["creativity"]
        assert required["risk_tolerance"] > suggested["risk_tolerance"]

    def test_clamped_at_one(self) -> None:
        pivoted = force_pivot({"creativity": 0.95, "risk_tolerance": 0.95}, strength="required")
        assert pivoted["creativity"] == 1.0
        assert pivoted["risk_tolerance"] == 1.0


class TestAdaptWiring:
    def test_adapts_with_v2_axes_when_flag_on(self, temp_workspace: Path) -> None:
        from evolver.gep.feature_flags import invalidate_cache, set_flag

        events = [
            {"outcome": {"status": "failed"}},
            {"outcome": {"status": "failed"}},
        ]
        set_flag("enable_personality_v2", True)
        invalidate_cache()
        try:
            adapted = adapt_personality(PERSONALITY_V2_DEFAULTS.copy(), events)
            # All five axes survive the adaptation round-trip.
            assert set(adapted) == set(AXES_V2)
        finally:
            set_flag("enable_personality_v2", False)
            invalidate_cache()

    def test_adapt_flag_off_keeps_three_axes(self, temp_workspace: Path) -> None:
        adapted = adapt_personality({"rigor": 0.5, "creativity": 0.5, "risk_tolerance": 0.3}, [])
        assert "verbosity" not in adapted
