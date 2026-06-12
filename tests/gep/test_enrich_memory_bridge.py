"""Enrich phase + memory_bridge integration."""

from __future__ import annotations

import pytest

from evolver.evolve.pipeline.enrich import enrich_phase


@pytest.mark.asyncio
async def test_enrich_merges_living_memory_hints(temp_workspace):
    ctx = {
        "signals": ["log_error"],
        "genes": [],
        "capsules": [],
        "living_memory": {
            "loaded": True,
            "high_friction_points": [
                {
                    "id": "fp_enrich_1",
                    "category": "solidify",
                    "rule_id": "solidify_guard",
                    "description": "solidify friction",
                }
            ],
            "recent_friction_points": [],
        },
    }
    out = await enrich_phase(ctx)
    assert "living_memory_risk:solidify" in out["signals"]
    assert "livingMemoryHints" in out["memory_advice"]
    assert "autopoiesis:solidify_guard" in out["memory_advice"]["livingMemoryHints"]
    assert out["memory_graph_friction_synced"]["synced"] == 1
