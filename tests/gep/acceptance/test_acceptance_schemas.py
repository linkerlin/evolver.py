"""Tests for evolver.gep.acceptance.schemas (Sprint A1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from evolver.gep.acceptance.schemas import (
    HELD_OUT_TIERS,
    REGRESS_VERDICTS,
    AcceptanceResult,
    LayerKind,
    LayerMetric,
    RepeatObs,
)


class TestRepeatObs:
    def test_minimal(self) -> None:
        obs = RepeatObs(repeat_index=0, score=0.5)
        assert obs.score == 0.5
        assert obs.denominator is None

    def test_score_bounds(self) -> None:
        RepeatObs(repeat_index=0, score=0.0)
        RepeatObs(repeat_index=0, score=1.0)
        with pytest.raises(ValidationError):
            RepeatObs(repeat_index=0, score=-0.01)
        with pytest.raises(ValidationError):
            RepeatObs(repeat_index=0, score=1.01)

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            RepeatObs(repeat_index=0, score=0.5, bogus=True)  # type: ignore[call-arg]


class TestLayerMetric:
    def test_defaults(self) -> None:
        m = LayerMetric(layer_id="T0_frozen@abc", kind="T0_frozen")
        assert m.kind == "T0_frozen"
        assert m.verdict == "unknown"
        assert m.baseline_repeats == []

    def test_invalid_kind(self) -> None:
        with pytest.raises(ValidationError):
            LayerMetric(layer_id="x", kind="T9_bogus")  # type: ignore[arg-type]

    def test_round_trip(self) -> None:
        m = LayerMetric(
            layer_id="held_in",
            kind="held_in",
            baseline_repeats=[RepeatObs(repeat_index=0, score=0.4, denominator=10)],
            candidate_repeats=[RepeatObs(repeat_index=0, score=0.6, denominator=10)],
            baseline_mean=0.4,
            candidate_mean=0.6,
            delta=0.2,
            verdict="improved",
        )
        dumped = m.model_dump()
        rebuilt = LayerMetric.model_validate(dumped)
        assert rebuilt.verdict == "improved"
        assert rebuilt.candidate_repeats[0].denominator == 10


class TestAcceptanceResult:
    def test_minimal(self) -> None:
        r = AcceptanceResult(accepted=False, reason="test")
        assert r.accepted is False
        assert r.layers == []
        assert r.repeats == 1
        assert r.format == "evolver.acceptance_gate.v0"

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            AcceptanceResult(accepted=True, reason="x", surprise=1)  # type: ignore[call-arg]


class TestConstants:
    def test_held_out_tiers_order(self) -> None:
        assert HELD_OUT_TIERS == ("T0_frozen", "T1_semantic", "T2_synthetic")

    def test_regress_verdicts(self) -> None:
        assert REGRESS_VERDICTS == frozenset({"dropped", "regresses"})
        # 'unchanged' / 'holds' / 'improved' / 'unknown' are NOT regressions
        assert "unchanged" not in REGRESS_VERDICTS
        assert "holds" not in REGRESS_VERDICTS


def test_layer_kind_literal_values() -> None:
    # sanity: the Literal members
    valid: tuple[LayerKind, ...] = ("held_in", "T0_frozen", "T1_semantic", "T2_synthetic")
    for k in valid:
        LayerMetric(layer_id=k, kind=k)
