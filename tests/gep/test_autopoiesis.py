"""Tests for evolver.gep.autopoiesis."""

from __future__ import annotations

import json

import pytest

from evolver.gep.autopoiesis import (
    apply_homeostasis,
    capture_friction_from_ctx,
    compute_viability,
    homeostasis_response,
    is_autopoiesis_enabled,
    is_autopoiesis_write_enabled,
    read_latest_tick,
    record_autopoiesis_tick,
    run_autopoiesis_tick,
    ViabilityReport,
)
from evolver.gep.self_report import SelfReport


def test_is_autopoiesis_enabled(monkeypatch):
    monkeypatch.delenv("EVOLVER_AUTOPOIESIS", raising=False)
    assert is_autopoiesis_enabled() is True
    monkeypatch.setenv("EVOLVER_AUTOPOIESIS", "0")
    assert is_autopoiesis_enabled() is False


def test_is_autopoiesis_write_enabled(monkeypatch):
    monkeypatch.delenv("EVOLVER_AUTOPOIESIS_WRITE", raising=False)
    assert is_autopoiesis_write_enabled() is True
    monkeypatch.setenv("EVOLVER_AUTOPOIESIS_WRITE", "0")
    assert is_autopoiesis_write_enabled() is False


def test_compute_viability_stable_ctx():
    ctx = {
        "genes": [{"id": "g1"}],
        "signals": [{"key": "s1"}, {"key": "s2"}],
        "hub_hit": {"reason": "tasks_found"},
    }
    report = compute_viability(ctx)
    assert report.status == "stable"
    assert report.score >= 0.65


def test_capture_friction_from_ctx_failure_diagnosis():
    report = SelfReport()
    ctx = {
        "failure_diagnosis": {
            "category": "runtime",
            "cause": "ModuleNotFoundError",
            "recommendation": "uv sync",
        }
    }
    count = capture_friction_from_ctx(report, ctx)
    assert count == 1
    assert report.friction_points[0].category == "runtime"


def test_homeostasis_critical_disables_drift():
    report = ViabilityReport(
        score=0.2,
        status="critical",
        boundary=0.2,
        metabolism=0.2,
        homeostasis=0.2,
        coupling=0.2,
        factors=["hub_offline"],
    )
    response = homeostasis_response(report)
    assert "force_repair_mode" in response["actions"]
    assert response["drift_allowed"] is False


def test_apply_homeostasis_mutates_ctx():
    ctx: dict = {"IS_RANDOM_DRIFT": True}
    apply_homeostasis(
        ctx,
        {
            "actions": ["force_repair_mode", "disable_drift"],
            "drift_allowed": False,
            "skip_hub_recommended": False,
        },
    )
    assert ctx["IS_RANDOM_DRIFT"] is False
    assert ctx["autopoiesis_repair_bias"] is True


def test_record_and_read_tick(monkeypatch, tmp_path):
    log_path = tmp_path / "autopoiesis.jsonl"
    monkeypatch.setenv("EVOLVER_AUTOPOIESIS_LOG_PATH", str(log_path))
    viability = compute_viability({"genes": [{"id": "g1"}], "signals": [{"k": 1}]})
    response = homeostasis_response(viability)
    event = record_autopoiesis_tick(
        run_id="run-1",
        viability=viability,
        response=response,
        self_report={"friction_summary": {"total": 0}},
    )
    assert event["type"] == "AutopoiesisTick"
    latest = read_latest_tick()
    assert latest is not None
    assert latest["self_report"]["friction_summary"]["total"] == 0


def test_run_autopoiesis_tick_disabled(monkeypatch):
    monkeypatch.setenv("EVOLVER_AUTOPOIESIS", "0")
    ctx = {"genes": [], "signals": []}
    out = run_autopoiesis_tick(ctx)
    assert "autopoiesis" not in out


def test_run_autopoiesis_tick_no_write(temp_workspace, monkeypatch):
    monkeypatch.setenv("EVOLVER_AUTOPOIESIS", "1")
    monkeypatch.setenv("EVOLVER_AUTOPOIESIS_WRITE", "0")
    monkeypatch.setenv("EVOLVER_AUTOPOIESIS_LOG_PATH", str(temp_workspace / "apo.jsonl"))
    ctx = {
        "run_id": "r99",
        "genes": [{"id": "g1"}],
        "signals": [{"key": "x"}],
        "hub_hit": {"reason": "assets_found"},
        "failure_diagnosis": {
            "category": "runtime",
            "cause": "error",
            "recommendation": "fix",
            "confidence": 0.8,
        },
    }
    out = run_autopoiesis_tick(ctx)
    assert "autopoiesis" in out
    assert out["autopoiesis"]["self_report"]["friction_summary"]["total"] >= 1
    assert out["autopoiesis"]["friction_captured_this_run"] >= 1
    assert not (temp_workspace / "memory" / "evolution" / "self_report.json").exists()


@pytest.mark.asyncio
async def test_autopoiesis_phase(temp_workspace, monkeypatch):
    from evolver.evolve.pipeline.autopoiesis import autopoiesis_phase

    monkeypatch.setenv("EVOLVER_AUTOPOIESIS_LOG_PATH", str(temp_workspace / "apo.jsonl"))
    monkeypatch.setenv("EVOLVER_AUTOPOIESIS_WRITE", "0")
    ctx = {"genes": [{"id": "g1"}], "signals": [{"k": 1}], "hub_hit": {"reason": "idle_skip"}}
    out = await autopoiesis_phase(ctx)
    assert out.get("autopoiesis") is not None
    assert "self_report" in out["autopoiesis"]
