"""Sprint 24.4: trigger engine — WFQ, value model, daily budget."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep.trigger_engine import (
    REACH_FULL_AT,
    DailyBudget,
    WeightedFairQueue,
    problem_value,
)


class TestWeightedFairQueue:
    def test_pick_order_by_weight(self) -> None:
        q = WeightedFairQueue()
        assert q.enqueue("a", 1.0, now=0.0)
        assert q.enqueue("b", 3.0, now=0.0)
        assert len(q) == 2
        assert q.pick(now=60.0) == "b"
        assert q.pick(now=60.0) == "a"
        assert q.pick(now=60.0) is None

    def test_dedup_on_enqueue(self) -> None:
        q = WeightedFairQueue()
        assert q.enqueue("x", 1.0)
        assert not q.enqueue("x", 9.0)
        assert "x" in q

    def test_age_boost_beats_weight_without_starvation(self) -> None:
        q = WeightedFairQueue()
        # old_low queued 16 min before new_high: its capped age boost
        # (log2(1+16)≈4) overcomes the +1 weight gap despite less recency.
        q.enqueue("old_low", weight=1.0, now=0.0)
        q.enqueue("new_high", weight=2.0, now=960.0)
        priorities = q.peek_priorities(now=960.0)
        assert priorities["old_low"] > priorities["new_high"]
        assert q.pick(now=960.0) == "old_low"

    def test_age_boost_capped(self) -> None:
        q = WeightedFairQueue()
        q.enqueue("ancient", 1.0, now=0.0)
        priorities = q.peek_priorities(now=10 * 86400.0)
        assert priorities["ancient"] == pytest.approx(1.0 + 4.0)


class TestProblemValue:
    def test_formula(self) -> None:
        score = problem_value(
            severity=0.8, reach_count=15, strategic_fit=0.9, novelty=0.5, cost_est=1.0
        )
        expected = 0.8 * (15 / REACH_FULL_AT) * 0.9 * 1.5 / 2.0
        assert score == pytest.approx(expected)

    def test_reach_saturates_at_fixed_scale(self) -> None:
        at_cap = problem_value(
            reach_count=REACH_FULL_AT, severity=1.0, strategic_fit=1.0, cost_est=0.0
        )
        beyond = problem_value(reach_count=10000, severity=1.0, strategic_fit=1.0, cost_est=0.0)
        assert at_cap == pytest.approx(1.0)
        assert beyond == pytest.approx(1.0)

    def test_unclassified_default_fit_is_conservative(self) -> None:
        unclassified = problem_value(severity=1.0, reach_count=30)
        classified = problem_value(severity=1.0, reach_count=30, strategic_fit=0.9)
        assert unclassified < classified * 0.5


class TestDailyBudget:
    def test_unlimited_when_caps_zero(self, temp_workspace: Path) -> None:
        b = DailyBudget(path=temp_workspace / "budget.json")
        for _ in range(5):
            assert b.can_fire()
            b.consume()

    def test_cycle_cap_blocks(self, temp_workspace: Path) -> None:
        b = DailyBudget(path=temp_workspace / "budget.json", max_cycles_per_day=2)
        b.consume()
        assert b.can_fire()
        b.consume()
        assert not b.can_fire()

    def test_token_cap_respects_incoming_cost(self, temp_workspace: Path) -> None:
        b = DailyBudget(
            path=temp_workspace / "budget.json",
            max_cycles_per_day=99,
            max_tokens_per_day=100,
        )
        assert b.can_fire(tokens=90)
        b.consume(tokens=90)
        assert not b.can_fire(tokens=20)

    def test_per_pattern_cap(self, temp_workspace: Path) -> None:
        b = DailyBudget(
            path=temp_workspace / "budget.json",
            max_cycles_per_day=99,
            per_pattern_cap=1,
        )
        assert b.can_fire(pattern="repair_loop")
        b.consume(pattern="repair_loop")
        assert not b.can_fire(pattern="repair_loop")
        assert b.can_fire(pattern="other")

    def test_date_rollover_resets(self, temp_workspace: Path) -> None:
        path = temp_workspace / "budget.json"
        b = DailyBudget(path=path, max_cycles_per_day=1)
        b.consume()
        assert not b.can_fire()

        # Simulate local-date rollover: any state access re-checks the date.
        b._state["date"] = "2000-01-01"
        assert b.can_fire()
        assert b.snapshot()["cycles"] == 0
