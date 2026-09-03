"""Feedback-adaptive mutation bias — EvoX adaptive-mutation-rate harvest (v1.106.0).

Degraded streak → repair bias; converged plateau (stddev < 0.01, mean ≥
threshold) → novelty pivot; mixed/insufficient samples stay neutral. Policy
weights shift and re-normalize; the verdict rides in policy["adaptive"].
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep.adaptive import apply_adaptive_bias, feedback_mutation_bias

BASE_POLICY = {"policy": "balanced", "repair": 0.34, "optimize": 0.33, "innovate": 0.33}


def _rows(scores: list[float], *, success: bool = True) -> list[dict]:
    return [{"primary_score": s, "success": success} for s in scores]


class TestBiasVerdicts:
    def test_insufficient_feedback_is_neutral(self) -> None:
        bias = feedback_mutation_bias(_rows([0.1, 0.2]))
        assert bias["explore_boost"] == 0 and bias["mode"] == "neutral"

    def test_empty_journal_is_neutral(self) -> None:
        bias = feedback_mutation_bias([])
        assert bias["explore_boost"] == 0 and bias["mode"] == "neutral"

    def test_degraded_streak_demands_repair(self) -> None:
        bias = feedback_mutation_bias(_rows([0.1, 0.2, 0.15, 0.3]))
        assert bias["explore_boost"] == -1
        assert bias["mode"] == "repair_bias"
        assert bias["degraded_streak"] == 4

    def test_failures_count_as_degraded_even_with_scores(self) -> None:
        rows = [{"primary_score": 0.9, "success": False}] * 3
        bias = feedback_mutation_bias(rows)
        assert bias["explore_boost"] == -1

    def test_converged_plateau_pivots_to_novelty(self) -> None:
        bias = feedback_mutation_bias(_rows([0.85, 0.85, 0.85, 0.85]))
        assert bias["explore_boost"] == 1
        assert bias["mode"] == "explore_plateau"
        assert bias["stddev"] == 0.0

    def test_converged_but_low_is_not_a_plateau(self) -> None:
        bias = feedback_mutation_bias(_rows([0.2, 0.2, 0.2]))
        # All-degraded also matches the streak rule first — still repair bias.
        assert bias["explore_boost"] == -1

    def test_mixed_outcomes_stay_balanced(self) -> None:
        bias = feedback_mutation_bias(_rows([0.9, 0.2, 0.7, 0.5]))
        assert bias["explore_boost"] == 0 and bias["mode"] == "balanced"


class TestPolicyBlending:
    def test_neutral_bias_keeps_weights_and_adds_verdict(self) -> None:
        bias = feedback_mutation_bias([])
        shifted = apply_adaptive_bias(dict(BASE_POLICY), bias)
        assert shifted["repair"] == BASE_POLICY["repair"]
        assert shifted["innovate"] == BASE_POLICY["innovate"]
        assert shifted["adaptive"]["mode"] == "neutral"

    def test_plateau_shifts_toward_innovate_and_normalizes(self) -> None:
        bias = feedback_mutation_bias(_rows([0.9, 0.9, 0.9]))
        shifted = apply_adaptive_bias(dict(BASE_POLICY), bias)
        assert shifted["innovate"] > BASE_POLICY["innovate"]
        assert shifted["repair"] < BASE_POLICY["repair"]
        total = shifted["repair"] + shifted["optimize"] + shifted["innovate"]
        assert abs(total - 1.0) < 0.02  # rounding tolerance
        assert shifted["adaptive"]["mode"] == "explore_plateau"

    def test_degraded_streak_shifts_toward_repair(self) -> None:
        bias = feedback_mutation_bias(_rows([0.1, 0.1, 0.1]))
        shifted = apply_adaptive_bias(dict(BASE_POLICY), bias)
        assert shifted["repair"] > BASE_POLICY["repair"]
        assert shifted["innovate"] < BASE_POLICY["innovate"]
        assert shifted["adaptive"]["mode"] == "repair_bias"


class TestPipelineWiring:
    def test_policy_computation_reads_feedback_journal(self, temp_workspace: Path) -> None:
        from evolver.evolve.pipeline.select import compute_adaptive_strategy_policy
        from evolver.gep.feedback import EvaluationFeedback, record_feedback

        for _ in range(3):
            record_feedback(EvaluationFeedback(primary_score=0.9))

        policy = compute_adaptive_strategy_policy({"signals": []})
        assert policy["adaptive"]["mode"] == "explore_plateau"
        assert policy["innovate"] > 0.33

    def test_disabled_via_config(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.evolve.pipeline.select import compute_adaptive_strategy_policy
        from evolver.gep.feedback import EvaluationFeedback, record_feedback

        for _ in range(3):
            record_feedback(EvaluationFeedback(primary_score=0.9))
        monkeypatch.setattr("evolver.config.ADAPTIVE_MUTATION_ENABLED", False)

        policy = compute_adaptive_strategy_policy({"signals": []})
        assert "adaptive" not in policy
        assert policy["innovate"] == 0.33
