"""Sprint 22.1 wiring: event history + gap outcome inference in signals_phase.

Closes open loops #1/#2 from the methodology audit (演进方案.md §13.3).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.evolve.pipeline.signals import signals_phase


def _seed_evolution_event(intent: str = "optimize", signals: list[str] | None = None) -> None:
    from evolver.gep.asset_store import append_event_jsonl

    append_event_jsonl(
        {
            "type": "EvolutionEvent",
            "id": f"evt_{intent}_{signals}",
            "intent": intent,
            "signals": signals or [],
            "genes_used": [],
            "blast_radius": {"files": 1, "lines": 2},
            "outcome": {"status": "success", "score": 1.0},
        }
    )


@pytest.mark.asyncio
async def test_event_history_disabled_by_default(temp_workspace: Path) -> None:
    _seed_evolution_event()
    ctx = await signals_phase({})
    assert ctx["recent_events"] == []


@pytest.mark.asyncio
async def test_event_history_wired_when_enabled(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOLVER_FF_ENABLE_EVENT_HISTORY", "true")
    _seed_evolution_event("repair", ["log_error"])
    ctx = await signals_phase({})
    assert len(ctx["recent_events"]) == 1
    assert ctx["recent_events"][0]["intent"] == "repair"


@pytest.mark.asyncio
async def test_gap_outcome_inference_records_success(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evolver.gep.memory_graph import read_all, record_attempt

    monkeypatch.setenv("EVOLVER_FF_ENABLE_GAP_OUTCOME_INFERENCE", "true")
    record_attempt(signals=["errsig:boom"], selected_gene={"id": "gene_x"}, run_id="r1")

    await signals_phase({})  # empty corpus => errors cleared => success

    outcomes = [e for e in read_all(limit=50) if e.get("kind") == "outcome"]
    assert len(outcomes) == 1
    assert outcomes[0]["outcome"]["status"] == "success"
    assert outcomes[0]["gene"]["id"] == "gene_x"

    # Second cycle must not double-record (outcome_recorded guard).
    await signals_phase({})
    outcomes = [e for e in read_all(limit=50) if e.get("kind") == "outcome"]
    assert len(outcomes) == 1


@pytest.mark.asyncio
async def test_gap_outcome_inference_disabled_by_default(temp_workspace: Path) -> None:
    from evolver.gep.memory_graph import read_all, record_attempt

    record_attempt(signals=["errsig:boom"], selected_gene={"id": "gene_x"}, run_id="r1")
    await signals_phase({})
    outcomes = [e for e in read_all(limit=50) if e.get("kind") == "outcome"]
    assert outcomes == []


@pytest.mark.asyncio
async def test_gap_outcome_inference_marks_persisting_error_failed(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evolver.gep.memory_graph import read_all, record_attempt

    monkeypatch.setenv("EVOLVER_FF_ENABLE_GAP_OUTCOME_INFERENCE", "true")
    record_attempt(signals=["errsig:boom"], selected_gene={"id": "gene_y"}, run_id="r2")

    await signals_phase({"memory_snippet": "ValueError: boom again"})

    outcomes = [e for e in read_all(limit=50) if e.get("kind") == "outcome"]
    assert len(outcomes) == 1
    assert outcomes[0]["outcome"]["status"] == "failed"
