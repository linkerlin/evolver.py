"""Bidirectional living_memory ↔ memory_graph sync tests."""

from __future__ import annotations

import pytest

from evolver.gep import memory_graph as mg
from evolver.gep.memory_bridge import (
    MEMORY_GRAPH_BAN_PREFIX,
    MEMORY_GRAPH_PREFER_PREFIX,
    bidirectional_memory_sync,
    build_memory_sync_summary,
    capture_memory_graph_bans_as_friction,
    living_memory_score_adjustment,
    memory_graph_signal_hints,
    merge_bidirectional_advice,
    reinforce_solidify_failure_in_graph,
    serialize_memory_advice,
    sync_living_friction_to_memory_graph,
)
from evolver.gep.self_report import SelfReport


def test_memory_graph_signal_hints_ban_and_prefer():
    advice = {
        "bannedGeneIds": {"gene_bad"},
        "solidifyPreferredGeneId": "gene_good",
        "frictionCategories": ["solidify"],
    }
    hints = memory_graph_signal_hints(advice)
    assert f"{MEMORY_GRAPH_BAN_PREFIX}gene_bad" in hints
    assert f"{MEMORY_GRAPH_PREFER_PREFIX}gene_good" in hints
    assert "memory_graph_friction:solidify" in hints


def test_merge_bidirectional_advice_unifies_hints():
    advice = {"bannedGeneIds": {"gene_x"}, "explanation": "base"}
    memory = {
        "loaded": True,
        "high_friction_points": [{"category": "runtime", "id": "fp1"}],
    }
    merged = merge_bidirectional_advice(advice, memory)
    assert "living_memory_risk:runtime" in merged["livingMemoryHints"]
    assert f"{MEMORY_GRAPH_BAN_PREFIX}gene_x" in merged["livingMemoryHints"]
    assert "memoryGraphHints" in merged


def test_sync_living_friction_dedupes(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))
    memory = {
        "loaded": True,
        "high_friction_points": [
            {
                "id": "fp_1",
                "category": "hub_offline",
                "description": "hub down",
            }
        ],
        "recent_friction_points": [],
    }
    first = sync_living_friction_to_memory_graph(memory, signals=["log_error"])
    assert first["synced"] == 1
    second = sync_living_friction_to_memory_graph(memory, signals=["log_error"])
    assert second["synced"] == 0
    assert second["skipped"] == 1
    events = mg.try_read_memory_graph_events()
    assert sum(1 for e in events if e.get("kind") == "friction") == 1


def test_bidirectional_memory_sync_merges_signals():
    advice = {"bannedGeneIds": set(), "explanation": ""}
    memory = {
        "loaded": True,
        "high_friction_points": [{"category": "solidify", "id": "fp2"}],
    }
    out = bidirectional_memory_sync(
        living_memory=memory,
        advice=advice,
        signals=["log_error"],
    )
    assert "living_memory_risk:solidify" in out["signals"]
    assert out["signals_added"]


def test_memory_graph_ban_hint_penalizes_gene():
    delta = living_memory_score_adjustment(
        {"id": "gene_bad", "signals_match": []},
        living_memory_hints=[f"{MEMORY_GRAPH_BAN_PREFIX}gene_bad"],
        signals=[],
    )
    assert delta < -0.4


def test_memory_graph_prefer_hint_boosts_gene():
    delta = living_memory_score_adjustment(
        {"id": "gene_good", "signals_match": []},
        living_memory_hints=[f"{MEMORY_GRAPH_PREFER_PREFIX}gene_good"],
        signals=[],
    )
    assert delta > 0.3


def test_capture_memory_graph_bans_as_friction_once(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))
    report = SelfReport()
    advice = {"bannedGeneIds": {"gene_repeat_fail"}}
    n1 = capture_memory_graph_bans_as_friction(report, advice)
    n2 = capture_memory_graph_bans_as_friction(report, advice)
    assert n1 == 1
    assert n2 == 0
    assert len(report.friction_points) == 1
    assert report.friction_points[0].category == "memory_graph"


def test_serialize_memory_advice_converts_banned_set():
    out = serialize_memory_advice({"bannedGeneIds": {"g1", "g2"}, "explanation": "x"})
    assert out is not None
    assert set(out["bannedGeneIds"]) == {"g1", "g2"}


def test_build_memory_sync_summary(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))
    mg.record_friction_observation(
        signals=["err"],
        friction={"id": "fp_s", "category": "solidify", "description": "d"},
    )
    summary = build_memory_sync_summary(
        last_run={
            "signals": ["err"],
            "memory_graph_friction_synced": {"synced": 2, "ids": ["a", "b"]},
        }
    )
    assert summary["friction_events_in_graph"] == 1
    assert "solidify" in summary["friction_categories"]
    assert summary["last_run_friction_synced"]["synced"] == 2


def test_reinforce_solidify_failure_in_graph(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))
    result = reinforce_solidify_failure_in_graph(
        {"signals": ["e"], "selected_gene_id": "gene_z", "run_id": "r1"},
        error="tests failed",
    )
    assert result["gene_id"] == "gene_z"
    events = mg.try_read_memory_graph_events()
    assert any(e.get("source") == "solidify_failure" for e in events)


def test_friction_events_surface_in_advice(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))
    signals = ["error_timeout"]
    mg.record_friction_observation(
        signals=signals,
        friction={"id": "fp3", "category": "solidify", "description": "x"},
    )
    advice = mg.get_memory_advice(signals=signals, genes=[])
    assert "solidify" in advice.get("frictionCategories", [])
