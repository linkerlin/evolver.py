"""Tests for evolver.gep.acceptance.gate (Sprint A1 decision logic)."""

from __future__ import annotations

import pytest

from evolver.gep.acceptance.gate import classify_rate, decide, mean_of
from evolver.gep.acceptance.schemas import LayerMetric, RepeatObs


def _rate_layer(
    kind: str,
    base: float,
    cand: float,
    *,
    denom: int = 10,
    verdict: str | None = None,
) -> LayerMetric:
    """Build a rate-style layer with single repeats and an explicit verdict."""
    return LayerMetric(
        layer_id=f"{kind}@test",
        kind=kind,  # type: ignore[arg-type]
        baseline_repeats=[RepeatObs(repeat_index=0, score=base, denominator=denom)],
        candidate_repeats=[RepeatObs(repeat_index=0, score=cand, denominator=denom)],
        baseline_mean=base,
        candidate_mean=cand,
        delta=cand - base,
        verdict=verdict if verdict else "unknown",  # type: ignore[arg-type]
    )


class TestMeanOf:
    def test_empty(self) -> None:
        assert mean_of([]) == 0.0

    def test_single(self) -> None:
        assert mean_of([RepeatObs(repeat_index=0, score=0.5)]) == 0.5

    def test_multiple(self) -> None:
        reps = [
            RepeatObs(repeat_index=0, score=0.4),
            RepeatObs(repeat_index=1, score=0.6),
            RepeatObs(repeat_index=2, score=0.5),
        ]
        assert mean_of(reps) == pytest.approx(0.5)


class TestClassifyRate:
    def test_improved(self) -> None:
        b, c, d, v = classify_rate(
            [RepeatObs(repeat_index=0, score=0.4)],
            [RepeatObs(repeat_index=0, score=0.6)],
        )
        assert (b, c) == (0.4, 0.6)
        assert d == pytest.approx(0.2)
        assert v == "improved"

    def test_dropped(self) -> None:
        _, _, _, v = classify_rate(
            [RepeatObs(repeat_index=0, score=0.6)],
            [RepeatObs(repeat_index=0, score=0.4)],
        )
        assert v == "dropped"

    def test_unchanged_within_epsilon(self) -> None:
        _, _, _, v = classify_rate(
            [RepeatObs(repeat_index=0, score=0.5)],
            [RepeatObs(repeat_index=0, score=0.52)],
            epsilon=0.05,
        )
        assert v == "unchanged"

    def test_epsilon_boundary(self) -> None:
        # delta exactly == epsilon → not > epsilon → unchanged
        _, _, _, v = classify_rate(
            [RepeatObs(repeat_index=0, score=0.5)],
            [RepeatObs(repeat_index=0, score=0.6)],
            epsilon=0.1,
        )
        assert v == "unchanged"


class TestDecideFullMode:
    def test_held_in_improved_t0_ok_accepts(self) -> None:
        layers = [
            _rate_layer("held_in", 0.4, 0.6, verdict="improved"),
            _rate_layer("T0_frozen", 0.8, 0.8, verdict="unchanged"),
        ]
        result = decide(layers)
        assert result.accepted is True
        assert result.reason == "held_in_improved_and_no_tier_regressed"

    def test_held_in_not_improved_rejects(self) -> None:
        layers = [
            _rate_layer("held_in", 0.5, 0.5, verdict="unchanged"),
            _rate_layer("T0_frozen", 0.8, 0.8, verdict="unchanged"),
        ]
        result = decide(layers)
        assert result.accepted is False
        assert result.reason == "held_in_not_improved"

    def test_t0_dropped_rejects_even_if_held_in_improved(self) -> None:
        layers = [
            _rate_layer("held_in", 0.4, 0.6, verdict="improved"),
            _rate_layer("T0_frozen", 0.8, 0.7, verdict="dropped"),
        ]
        result = decide(layers)
        assert result.accepted is False
        assert result.reason == "T0_frozen_regressed"

    def test_t1_regresses_rejects(self) -> None:
        layers = [
            _rate_layer("held_in", 0.4, 0.6, verdict="improved"),
            LayerMetric(
                layer_id="T1@x",
                kind="T1_semantic",
                verdict="regresses",
            ),
        ]
        result = decide(layers)
        assert result.accepted is False
        assert result.reason == "T1_semantic_regressed"


class TestDecideT0OnlyDegraded:
    def test_no_held_in_no_regression_accepts(self) -> None:
        layers = [_rate_layer("T0_frozen", 0.8, 0.8, verdict="unchanged")]
        result = decide(layers)
        assert result.accepted is True
        assert result.reason == "t0_only_no_regression"

    def test_no_held_in_t0_dropped_rejects(self) -> None:
        layers = [_rate_layer("T0_frozen", 0.8, 0.6, verdict="dropped")]
        result = decide(layers)
        assert result.accepted is False
        assert result.reason == "T0_frozen_regressed"

    def test_empty_layers_accepts_degraded(self) -> None:
        # Nothing ran → nothing regressed → degraded accept.
        result = decide([])
        assert result.accepted is True
        assert result.reason == "t0_only_no_regression"


class TestDecideStrictT2:
    def test_t2_unknown_rejects_under_strict(self) -> None:
        layers = [
            _rate_layer("held_in", 0.4, 0.6, verdict="improved"),
            LayerMetric(layer_id="T2@x", kind="T2_synthetic", verdict="unknown"),
        ]
        result = decide(layers, strict_t2=True)
        assert result.accepted is False
        assert result.reason == "T2_unknown_under_strict"

    def test_t2_unknown_ok_when_not_strict(self) -> None:
        layers = [
            _rate_layer("held_in", 0.4, 0.6, verdict="improved"),
            LayerMetric(layer_id="T2@x", kind="T2_synthetic", verdict="unknown"),
        ]
        result = decide(layers, strict_t2=False)
        assert result.accepted is True

    def test_t2_regresses_always_rejects(self) -> None:
        layers = [
            _rate_layer("held_in", 0.4, 0.6, verdict="improved"),
            LayerMetric(layer_id="T2@x", kind="T2_synthetic", verdict="regresses"),
        ]
        assert decide(layers, strict_t2=False).accepted is False
        assert decide(layers, strict_t2=True).accepted is False
