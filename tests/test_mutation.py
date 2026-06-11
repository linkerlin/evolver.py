"""Tests for evolver.gep.mutation — equivalent to evolver/test/mutation.test.js."""

from __future__ import annotations

from evolver.gep import mutation


def test_clamp01() -> None:
    assert mutation.clamp01(0.5) == 0.5
    assert mutation.clamp01(-0.5) == 0.0
    assert mutation.clamp01(1.5) == 1.0
    assert mutation.clamp01(float("nan")) == 0.0
    assert mutation.clamp01(None) == 0.0


def test_is_high_risk_personality() -> None:
    assert mutation.is_high_risk_personality({"rigor": 0.3}) is True
    assert mutation.is_high_risk_personality({"risk_tolerance": 0.7}) is True
    assert mutation.is_high_risk_personality({"rigor": 0.8, "risk_tolerance": 0.2}) is False


def test_is_high_risk_mutation_allowed() -> None:
    assert mutation.is_high_risk_mutation_allowed({"rigor": 0.8, "risk_tolerance": 0.3}) is True
    assert mutation.is_high_risk_mutation_allowed({"rigor": 0.4, "risk_tolerance": 0.3}) is False
    assert mutation.is_high_risk_mutation_allowed({"rigor": 0.8, "risk_tolerance": 0.6}) is False


def test_build_mutation_repair_for_errors() -> None:
    m = mutation.build_mutation(signals=["log_error", "errsig:something"])
    assert mutation.is_valid_mutation(m)
    assert m["category"] == "repair"


def test_build_mutation_innovate_for_drift() -> None:
    m = mutation.build_mutation(signals=["stable_success_plateau"], drift_enabled=True)
    assert m["category"] == "innovate"


def test_build_mutation_downgrades_high_risk_personality() -> None:
    personality = {"rigor": 0.3, "risk_tolerance": 0.8, "creativity": 0.5}
    m = mutation.build_mutation(signals=["user_feature_request"], personality_state=personality)
    assert m["category"] == "optimize"


def test_normalize_mutation_defaults() -> None:
    m = mutation.normalize_mutation({})
    assert mutation.is_valid_mutation(m)
    assert m["category"] == "optimize"
    assert m["risk_level"] == "low"


def test_is_valid_mutation_rejects_invalid() -> None:
    assert mutation.is_valid_mutation(None) is False
    assert mutation.is_valid_mutation({}) is False
    assert (
        mutation.is_valid_mutation({"type": "Mutation", "id": "x", "category": "destroy"}) is False
    )
