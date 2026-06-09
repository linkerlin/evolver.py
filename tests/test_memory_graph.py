"""Tests for evolver.gep.memory_graph — equivalent to evolver/test/memoryGraph.test.js."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep import memory_graph as mg


def test_compute_signal_key_order_independent() -> None:
    k1 = mg.compute_signal_key(["error_a", "error_b"])
    k2 = mg.compute_signal_key(["error_b", "error_a"])
    assert k1 == k2


def test_compute_signal_key_different_inputs() -> None:
    k1 = mg.compute_signal_key(["error_a"])
    k2 = mg.compute_signal_key(["error_b"])
    assert k1 != k2


def test_compute_signal_key_empty() -> None:
    k = mg.compute_signal_key([])
    assert isinstance(k, str) and len(k) > 0


def test_compute_signal_key_trims_whitespace() -> None:
    k1 = mg.compute_signal_key(["  error_a  "])
    k2 = mg.compute_signal_key(["error_a"])
    assert k1 == k2


def test_compute_signal_key_deduplicates() -> None:
    k1 = mg.compute_signal_key(["error_a", "error_a"])
    k2 = mg.compute_signal_key(["error_a"])
    assert k1 == k2


def test_record_signal_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))
    result = mg.record_signal_snapshot(signals=["error_crash"], observations={"test_mode": True})
    assert result["kind"] == "signal"
    events = mg.try_read_memory_graph_events()
    assert len(events) == 1
    assert events[0]["type"] == "MemoryGraphEvent"
    assert events[0]["kind"] == "signal"


def test_record_hypothesis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))
    result = mg.record_hypothesis(
        signals=["error_crash"],
        selected_gene={"id": "gene_test_123", "category": "repair"},
    )
    assert isinstance(result["hypothesisId"], str)
    assert isinstance(result["signalKey"], str)
    events = mg.try_read_memory_graph_events()
    assert events[-1]["kind"] == "hypothesis"


def test_get_memory_advice_bans_failing_gene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))
    signals = ["log_error", "recurring_error"]
    key = mg.compute_signal_key(signals)
    for i in range(5):
        mg.record_outcome(
            signals=signals,
            selected_gene={"id": "gene_repair_failing", "category": "repair"},
            outcome={"status": "failed", "score": 0},
            blast_radius={"files": 0, "lines": 0},
        )
    advice = mg.get_memory_advice(
        signals=signals,
        genes=[{"id": "gene_repair_failing", "type": "Gene"}],
    )
    assert "gene_repair_failing" in advice["bannedGeneIds"]


def test_get_memory_advice_drift_respects_ban(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))
    signals = ["log_error", "recurring_error"]
    for _ in range(5):
        mg.record_outcome(
            signals=signals,
            selected_gene={"id": "gene_repair_failing", "category": "repair"},
            outcome={"status": "failed", "score": 0},
        )
    advice = mg.get_memory_advice(
        signals=signals,
        genes=[{"id": "gene_repair_failing", "type": "Gene"}],
        drift_enabled=True,
    )
    assert "gene_repair_failing" in advice["bannedGeneIds"]
