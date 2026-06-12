"""P3 Autopoiesis integration: selector scoring, solidify success, preflight abort."""

from __future__ import annotations

import asyncio
import json

import pytest

from evolver.evolve import guards
from evolver.evolve.runner import _run_single_cycle
from evolver.gep import selector
from evolver.gep.autopoiesis import (
    capture_solidify_success,
    clear_preflight_abort_report,
    read_preflight_abort_report,
    run_preflight_abort_self_report,
)
from evolver.gep import memory_graph as mg
from evolver.gep.cognition import post_solidify_hooks
from evolver.gep.memory_bridge import living_memory_score_adjustment


GENES = [
    {
        "id": "gene_alpha",
        "category": "repair",
        "signals_match": ["solidify"],
        "summary": "solidify specialist",
    },
    {
        "id": "gene_beta",
        "category": "repair",
        "signals_match": ["error", "exception"],
        "summary": "generic repair",
    },
]


def test_living_memory_penalizes_matching_gene():
    adj = living_memory_score_adjustment(
        {"id": "gene_solidify_guard", "signals_match": ["solidify"]},
        living_memory_hints=["living_memory_risk:solidify"],
        signals=["error"],
    )
    assert adj < 0


def test_living_memory_boosts_repair_under_repair_loop():
    adj = living_memory_score_adjustment(
        GENES[1],
        living_memory_hints=[],
        signals=["repair_loop", "error"],
    )
    assert adj > 0


def test_selector_prefers_non_penalized_gene():
    result = selector.select_gene(
        GENES,
        ["error", "solidify"],
        {"livingMemoryHints": ["living_memory_risk:solidify"]},
    )
    assert result["selected"]["id"] == "gene_beta"


def test_preflight_abort_self_report_no_write(temp_workspace, monkeypatch):
    monkeypatch.setenv("EVOLVER_AUTOPOIESIS_WRITE", "0")
    data = run_preflight_abort_self_report("system load too high")
    assert data["friction_summary"]["total"] == 1
    assert not (temp_workspace / "memory" / "evolution" / "self_report.json").exists()
    persisted = read_preflight_abort_report()
    assert persisted is not None
    assert persisted["reason"] == "system load too high"
    assert persisted["report"]["friction_summary"]["total"] == 1
    clear_preflight_abort_report()
    assert read_preflight_abort_report() is None


def test_capture_solidify_success_writes_lessons(temp_workspace, monkeypatch):
    monkeypatch.setenv("EVOLVER_AUTOPOIESIS", "1")
    monkeypatch.setenv("EVOLVER_AUTOPOIESIS_WRITE", "1")
    (temp_workspace / "memory" / "evolution").mkdir(parents=True, exist_ok=True)
    (temp_workspace / ".evolver" / "gep").mkdir(parents=True, exist_ok=True)
    signals = ["error_timeout"]
    capture_solidify_success(
        {"outcome": {"status": "success"}},
        last_run={
            "selected_gene_id": "g1",
            "mutation": {"category": "repair"},
            "signals": signals,
        },
    )
    lessons = temp_workspace / "memory" / "evolution" / "LESSONS_LEARNED.md"
    assert lessons.exists()
    assert "solidify_success" in lessons.read_text(encoding="utf-8")
    advice = mg.get_memory_advice(signals=signals, genes=[{"id": "g1", "type": "Gene"}])
    assert advice["solidifyPreferredGeneId"] == "g1"


def test_post_solidify_hooks_calls_autopoiesis_success(temp_workspace, monkeypatch):
    monkeypatch.setenv("EVOLVER_AUTOPOIESIS", "1")
    monkeypatch.setenv("EVOLVER_AUTOPOIESIS_WRITE", "1")
    (temp_workspace / "memory" / "evolution").mkdir(parents=True, exist_ok=True)
    (temp_workspace / ".evolver" / "gep").mkdir(parents=True, exist_ok=True)
    hooks = post_solidify_hooks(
        {"outcome": {"status": "success"}},
        {"selected_gene_id": "g2", "mutation": {"category": "optimize"}, "signals": []},
    )
    assert hooks.get("autopoiesis_success") is True


@pytest.mark.asyncio
async def test_runner_preflight_abort_attaches_report(monkeypatch):
    from evolver.evolve.guards import PreflightResult

    async def _abort_preflight(**_kwargs):
        return PreflightResult(abort=True, reason="test abort")

    monkeypatch.setattr("evolver.evolve.guards.run_preflight_checks", _abort_preflight)
    monkeypatch.setenv("EVOLVER_AUTOPOIESIS", "1")
    monkeypatch.setenv("EVOLVER_AUTOPOIESIS_WRITE", "0")
    ctx = await _run_single_cycle()
    assert "autopoiesis_preflight_abort" in ctx
    assert ctx["autopoiesis_preflight_abort"]["friction_summary"]["total"] == 1


def test_repair_loop_hard_abort_when_degraded_off(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_REPAIR_LOOP_DEGRADED", "0")
    from evolver.gep.asset_store import append_event_jsonl
    from evolver.gep.paths import get_gep_assets_dir

    get_gep_assets_dir().mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        append_event_jsonl(
            {
                "type": "EvolutionEvent",
                "mutation": {"category": "repair"},
                "outcome": {"status": "failed"},
            }
        )
    result = asyncio.run(guards.run_preflight_checks(is_dry_run=False))
    assert result.abort is True
    assert result.repair_loop_degraded is False
