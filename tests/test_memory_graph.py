"""Tests for evolver.gep.memory_graph — equivalent to evolver/test/memoryGraph.test.js."""

from __future__ import annotations

import json
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


def test_get_memory_advice_bans_failing_gene(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_get_memory_advice_drift_respects_ban(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_record_signal_gene_preference_overrides_advice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))
    signals = ["error_timeout"]
    mg.record_signal_gene_preference(gene_id="gene_solidify_winner", signals=signals)
    advice = mg.get_memory_advice(
        signals=signals,
        genes=[
            {"id": "gene_solidify_winner", "type": "Gene"},
            {"id": "gene_other", "type": "Gene"},
        ],
    )
    assert advice["preferredGeneId"] == "gene_solidify_winner"
    assert advice["solidifyPreferredGeneId"] == "gene_solidify_winner"


# ---------------------------------------------------------------------------
# Regression tests for EvoMap/evolver#562 — inert (stable_no_error) outcomes
# must not build confidence, and a gene with GENE_INERT_BAN_STREAK consecutive
# trailing inert outcomes (and no real success) must be banned.
# ---------------------------------------------------------------------------

_INERT_GENE = {"id": "gene_auto_6279e076", "category": "repair"}
_INERT_SIGNALS = ["memory_missing"]


def _write_outcome_seq(
    tmp_path: Path, gene_id: str, signals: list[str], seq: list[dict[str, str]]
) -> None:
    """Write a chronological outcome sequence to the memory graph."""
    key = mg.compute_signal_key(signals)
    lines = []
    for i, o in enumerate(seq):
        lines.append(
            json.dumps(
                {
                    "type": "MemoryGraphEvent",
                    "kind": "outcome",
                    "id": f"mge562_{i}",
                    "ts": f"2026-06-01T00:00:{i:02d}.000Z",
                    "signal": {"key": key, "signals": signals},
                    "gene": {"id": gene_id, "category": "repair"},
                    "action": {"id": f"act562_{i}"},
                    "outcome": {
                        "status": o["status"],
                        "score": 0.15 if o["status"] == "failed" else 0.6,
                        "note": o["note"],
                    },
                }
            )
        )
    (tmp_path / "memory_graph.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _inert(n: int) -> list[dict[str, str]]:
    return [{"status": "success", "note": "stable_no_error|heuristic_delta|predictive"}] * n


def _real(n: int) -> list[dict[str, str]]:
    return [{"status": "success", "note": "error_cleared"}] * n


def test_562_inert_outcomes_do_not_build_confidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gene whose entire history is inert must NOT be preferred."""
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))
    _write_outcome_seq(tmp_path, _INERT_GENE["id"], _INERT_SIGNALS, _inert(20))
    advice = mg.get_memory_advice(
        signals=_INERT_SIGNALS, genes=[{**_INERT_GENE, "type": "Gene"}], drift_enabled=False
    )
    assert advice["preferredGeneId"] is None, (
        "zero-work successes must not count as positive evidence"
    )


def test_562_real_successes_do_build_confidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: the same gene WITH real successes IS preferred."""
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))
    _write_outcome_seq(tmp_path, _INERT_GENE["id"], _INERT_SIGNALS, _real(20))
    advice = mg.get_memory_advice(
        signals=_INERT_SIGNALS, genes=[{**_INERT_GENE, "type": "Gene"}], drift_enabled=False
    )
    assert advice["preferredGeneId"] == _INERT_GENE["id"]


def test_562_inert_streak_ban_at_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gene banned after GENE_INERT_BAN_STREAK consecutive inert outcomes."""
    from evolver.config import GENE_INERT_BAN_STREAK

    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))
    _write_outcome_seq(tmp_path, _INERT_GENE["id"], _INERT_SIGNALS, _inert(GENE_INERT_BAN_STREAK))
    for drift in (False, True):
        advice = mg.get_memory_advice(
            signals=_INERT_SIGNALS,
            genes=[{**_INERT_GENE, "type": "Gene"}],
            drift_enabled=drift,
        )
        assert _INERT_GENE["id"] in advice["bannedGeneIds"], (
            f"stuck-inert gene must be banned (drift={drift})"
        )


def test_562_not_banned_below_streak_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gene NOT banned below the streak threshold."""
    from evolver.config import GENE_INERT_BAN_STREAK

    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))
    _write_outcome_seq(
        tmp_path, _INERT_GENE["id"], _INERT_SIGNALS, _inert(GENE_INERT_BAN_STREAK - 1)
    )
    advice = mg.get_memory_advice(
        signals=_INERT_SIGNALS, genes=[{**_INERT_GENE, "type": "Gene"}], drift_enabled=False
    )
    assert _INERT_GENE["id"] not in advice["bannedGeneIds"]


def test_562_real_success_resets_inert_streak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single real success resets the consecutive inert streak."""
    from evolver.config import GENE_INERT_BAN_STREAK

    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))
    # 7 inert, 1 real, 7 inert => 14 total but only 7 trailing (< threshold).
    seq = _inert(GENE_INERT_BAN_STREAK - 1) + _real(1) + _inert(GENE_INERT_BAN_STREAK - 1)
    _write_outcome_seq(tmp_path, _INERT_GENE["id"], _INERT_SIGNALS, seq)
    advice = mg.get_memory_advice(
        signals=_INERT_SIGNALS, genes=[{**_INERT_GENE, "type": "Gene"}], drift_enabled=False
    )
    assert _INERT_GENE["id"] not in advice["bannedGeneIds"], (
        "a gene that ever does real work must not be punished for old idle cycles"
    )
