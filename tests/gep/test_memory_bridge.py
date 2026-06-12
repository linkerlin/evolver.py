"""Tests for evolver.gep.memory_bridge."""

from __future__ import annotations

from evolver.gep.memory_bridge import (
    living_memory_signal_hints,
    merge_hints_into_signals,
    merge_living_memory_into_advice,
)


def test_living_memory_signal_hints():
    memory = {
        "loaded": True,
        "high_friction_points": [
            {"category": "solidify", "rule_id": "solidify_guard"},
            {"category": "hub_offline"},
        ],
    }
    hints = living_memory_signal_hints(memory)
    assert "living_memory_risk:solidify" in hints
    assert "autopoiesis:solidify_guard" in hints
    assert "living_memory_risk:hub_offline" in hints


def test_merge_living_memory_into_advice():
    advice = {"explanation": "base", "bannedGeneIds": set()}
    memory = {
        "loaded": True,
        "high_friction_points": [{"category": "runtime", "rule_id": "runtime_guard"}],
    }
    merged = merge_living_memory_into_advice(advice, memory)
    assert "livingMemoryHints" in merged
    assert "living_memory_risk:runtime" in merged["livingMemoryHints"]
    assert "living_memory_hints" in merged["explanation"]


def test_merge_hints_into_signals():
    merged, added = merge_hints_into_signals(["log_error"], ["living_memory_risk:runtime"])
    assert merged == ["log_error", "living_memory_risk:runtime"]
    assert added == ["living_memory_risk:runtime"]
