"""Preflight abort signal injection in signals_phase."""

from __future__ import annotations

import pytest

from evolver.evolve.pipeline.hub import hub_phase
from evolver.evolve.pipeline.select import select_phase
from evolver.evolve.pipeline.signals import signals_phase
from evolver.gep.autopoiesis import apply_preflight_abort_recovery, preflight_abort_signal_keys


def test_preflight_abort_signal_keys_from_report(monkeypatch):
    monkeypatch.setattr(
        "evolver.gep.autopoiesis.read_preflight_abort_report",
        lambda: {
            "reason": "repair loop tripped",
            "report": {"friction_summary": {"total": 1}},
        },
    )
    keys = preflight_abort_signal_keys()
    assert "preflight_abort" in keys
    assert "autopoiesis:preflight_abort" in keys
    assert "preflight_abort:repair_loop_tripped" in keys


def test_preflight_abort_signal_keys_empty(monkeypatch):
    monkeypatch.setattr(
        "evolver.gep.autopoiesis.read_preflight_abort_report",
        lambda: None,
    )
    assert preflight_abort_signal_keys() == []


@pytest.mark.asyncio
async def test_signals_phase_merges_preflight_abort(monkeypatch, temp_workspace):
    monkeypatch.setattr(
        "evolver.gep.autopoiesis.read_preflight_abort_report",
        lambda: {
            "reason": "system load too high",
            "report": {"friction_summary": {"total": 1}},
        },
    )
    ctx = {
        "memory_snippet": "",
        "user_snippet": "",
        "session_log": "",
        "recent_master_log": "",
        "recent_events": [],
    }
    out = await signals_phase(ctx)
    assert "preflight_abort" in out["signals"]
    assert "autopoiesis:preflight_abort" in out["signals"]
    assert out["preflight_abort_signals_merged"]
    assert out.get("preflight_abort_recovery") is True
    assert out.get("autopoiesis_repair_bias") is True
    assert out.get("IS_RANDOM_DRIFT") is False
    assert out.get("skip_hub_calls") is True
    assert out.get("hub_skip_reason") == "preflight_abort_recovery"


@pytest.mark.asyncio
async def test_preflight_recovery_skips_hub_phase(monkeypatch, temp_workspace):
    monkeypatch.setattr(
        "evolver.gep.autopoiesis.read_preflight_abort_report",
        lambda: {"reason": "load high", "report": {}},
    )

    async def fail_fetch(*_a, **_k):
        raise AssertionError("hub should not be called during preflight recovery")

    monkeypatch.setattr("evolver.gep.a2a_protocol.fetch_tasks", fail_fetch)
    sig_out = await signals_phase(
        {
            "memory_snippet": "",
            "user_snippet": "",
            "session_log": "",
            "recent_master_log": "",
            "recent_events": [],
        }
    )
    hub_out = await hub_phase(sig_out)
    assert hub_out["hub_hit"]["reason"] == "idle_skip"
    assert hub_out.get("hub_skip_reason") == "preflight_abort_recovery"


@pytest.mark.asyncio
async def test_preflight_abort_recovery_forces_repair_mutation(monkeypatch, temp_workspace):
    monkeypatch.setattr(
        "evolver.gep.autopoiesis.read_preflight_abort_report",
        lambda: {
            "reason": "repair loop",
            "report": {"friction_summary": {"total": 1}},
        },
    )
    sig_ctx = {
        "memory_snippet": "",
        "user_snippet": "",
        "session_log": "",
        "recent_master_log": "",
        "recent_events": [],
    }
    sig_out = await signals_phase(sig_ctx)
    sel_out = await select_phase(
        {
            **sig_out,
            "memory_advice": {},
            "recent_events": [],
        }
    )
    assert sel_out["mutation"]["category"] == "repair"


def test_apply_preflight_abort_recovery_sets_flags(monkeypatch):
    monkeypatch.setattr(
        "evolver.gep.autopoiesis.read_preflight_abort_report",
        lambda: {"reason": "load high", "report": {}},
    )
    ctx: dict = {"signals": ["preflight_abort", "log_error"]}
    assert apply_preflight_abort_recovery(ctx) is True
    assert ctx["preflight_abort_reason"] == "load high"
    assert ctx["skip_hub_calls"] is True
    assert ctx["hub_skip_reason"] == "preflight_abort_recovery"
