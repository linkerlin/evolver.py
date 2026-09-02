"""S28.2 launch-failure honesty: zero tool calls is NOT behavioral evidence."""

from __future__ import annotations

import json

from evolver.gep.trajectory.builder import Trajectory, TrajectoryStats
from evolver.gep.trajectory.io import trajectory_to_dict


def _traj(tool_call_count: int) -> Trajectory:
    return Trajectory(
        session_id="s1",
        turns=[],
        stats=TrajectoryStats(
            turns=1,
            has_tool_calls=tool_call_count > 0,
            tool_call_count=tool_call_count,
        ),
    )


def test_zero_tool_calls_is_launch_failure() -> None:
    """A dead session is a launch failure, not evidence of agent behavior."""
    traj = _traj(0)
    assert traj.activity == "launch_failure"


def test_tool_calls_mean_active() -> None:
    traj = _traj(3)
    assert traj.activity == "active"


def test_activity_survives_serialization() -> None:
    """The classification rides the exported JSONL row for downstream signal
    consumers — no separate lookup needed."""
    row = trajectory_to_dict(_traj(0))
    assert row["activity"] == "launch_failure"
    assert json.loads(json.dumps(row))["activity"] == "launch_failure"
    assert trajectory_to_dict(_traj(2))["activity"] == "active"
