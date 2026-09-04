"""Degraded swarm feedback must force repair the way autopoiesis friction does."""

from __future__ import annotations

from pathlib import Path

from evolver.evolve.pipeline.select import select_phase
from evolver.gep.feedback import FEEDBACK_SIGNAL_DEGRADED


async def test_degraded_feedback_signal_forces_repair(temp_workspace: Path) -> None:
    _ = temp_workspace
    out = await select_phase(
        {
            "signals": [FEEDBACK_SIGNAL_DEGRADED],
            "genes": [],
            "capsules": [],
            "memory_advice": {},
            "recent_events": [],
        }
    )
    assert out["autopoiesis_repair_bias"] is True
    assert out["mutation"]["category"] == "repair"
