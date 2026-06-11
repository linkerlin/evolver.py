"""Tests for evolver.evolve.pipeline.select."""

from __future__ import annotations

from evolver.evolve.pipeline.select import compute_adaptive_strategy_policy


class TestComputeAdaptiveStrategyPolicy:
    def test_basic(self):
        ctx = {"signals": []}
        policy = compute_adaptive_strategy_policy(ctx)
        assert "policy" in policy
        assert "repair" in policy
        assert "optimize" in policy
        assert "innovate" in policy

    def test_force_innovation(self):
        ctx = {"signals": [], "IS_RANDOM_DRIFT": True}
        policy = compute_adaptive_strategy_policy(ctx)
        assert policy["force_innovation"] is True
