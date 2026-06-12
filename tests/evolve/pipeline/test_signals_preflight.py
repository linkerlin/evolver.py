"""Preflight abort signal injection in signals_phase."""

from __future__ import annotations

import pytest

from evolver.evolve.pipeline.signals import signals_phase
from evolver.gep.autopoiesis import preflight_abort_signal_keys


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
