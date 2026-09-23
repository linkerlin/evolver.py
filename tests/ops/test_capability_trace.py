"""Tests for evolver.ops.capability_trace (P2-10, round-73)."""

from __future__ import annotations

from evolver.ops.capability_trace import capability_trajectory


class TestCapabilityTrajectory:
    def test_zero_state_all_dims_zero(self) -> None:
        t = capability_trajectory(gated_cumulative=0, anchor_cases=0, env_count=80)
        assert all(d["pct"] == 0.0 for d in t["dimensions"])
        assert t["overall_pct"] == 0.0

    def test_at_target_clamps_to_100(self) -> None:
        t = capability_trajectory(gated_cumulative=100, anchor_cases=20, env_count=40)
        by_key = {d["key"]: d for d in t["dimensions"]}
        assert by_key["gated_cumulative"]["pct"] == 100.0
        assert by_key["anchor_cases"]["pct"] == 100.0
        # env headroom: budget 80 - usage 40 = 40 headroom vs target 20 → clamped
        assert by_key["env_headroom"]["pct"] == 100.0

    def test_partial_state(self) -> None:
        t = capability_trajectory(gated_cumulative=20, anchor_cases=8, env_count=80)
        by_key = {d["key"]: d for d in t["dimensions"]}
        assert by_key["gated_cumulative"]["pct"] == 50.0
        assert by_key["anchor_cases"]["pct"] == 50.0
        assert by_key["env_headroom"]["pct"] == 0.0, "zero headroom is zero progress"

    def test_env_headroom_inverted(self) -> None:
        # Spending LESS env budget is progress: usage 60 → headroom 20 = 100%.
        t = capability_trajectory(gated_cumulative=0, anchor_cases=0, env_count=60)
        by_key = {d["key"]: d for d in t["dimensions"]}
        assert by_key["env_headroom"]["pct"] == 100.0

    def test_overall_is_mean_of_dims(self) -> None:
        t = capability_trajectory(gated_cumulative=40, anchor_cases=16, env_count=78)
        # headroom: 80-78=2 vs target 20 → 10%
        assert t["overall_pct"] == round((100.0 + 100.0 + 10.0) / 3, 1)
