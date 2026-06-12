"""Cross-module Autopoiesis integration tests."""

from __future__ import annotations

import json

import pytest

from evolver.evolve.pipeline.hub import hub_phase
from evolver.evolve.pipeline.select import select_phase
from evolver.evolve.pipeline.signals import signals_phase
from evolver.gep.autopoiesis import (
    merge_autopoiesis_signals,
    persist_skip_hub_flag,
    consume_skip_hub_flag,
)
from evolver.gep.autopoiesis_rules import guard_check_signal_keys
from evolver.gep.mutation import build_mutation
from evolver.gep.self_report import SelfReport


@pytest.mark.asyncio
async def test_guard_rules_injected_in_signals_phase(temp_workspace):
    rules_path = temp_workspace / ".evolver" / "gep" / "autopoiesis_rules.json"
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(
        json.dumps(
            {
                "guard_checks": {
                    "runtime_guard": {
                        "signal_key": "autopoiesis:runtime_guard",
                        "autopoiesis": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    ctx = {
        "memory_snippet": "",
        "user_snippet": "",
        "session_log": "clean",
        "recent_master_log": "",
        "recent_events": [],
    }
    out = await signals_phase(ctx)
    assert "autopoiesis:runtime_guard" in out["signals"]


def test_merge_autopoiesis_signals_same_cycle():
    report = SelfReport()
    report.capture_friction("runtime", "err", "fix", auto_encode=False)
    report.friction_points[0].rule_id = "runtime_guard"
    ctx: dict = {"signals": ["log_error"]}
    added = merge_autopoiesis_signals(ctx, report)
    assert "autopoiesis:runtime_guard" in ctx["signals"]
    assert "autopoiesis:runtime_guard" in added


@pytest.mark.asyncio
async def test_repair_bias_forces_repair_mutation(temp_workspace, monkeypatch):
    monkeypatch.setenv("EVOLVER_AUTOPOIESIS_WRITE", "0")
    ctx = {
        "signals": ["stable_success_plateau"],
        "genes": [{"id": "g1", "category": "repair", "signals_match": ["repair_loop"]}],
        "capsules": [],
        "memory_advice": {},
        "IS_RANDOM_DRIFT": False,
        "autopoiesis_repair_bias": True,
        "recent_events": [],
    }
    out = await select_phase(ctx)
    assert out["mutation"]["category"] == "repair"
    assert "repair_loop" in out["mutation"]["trigger_signals"]


def test_force_category_build_mutation():
    m = build_mutation(signals=["user_feature_request"], force_category="repair")
    assert m["category"] == "repair"


@pytest.mark.asyncio
async def test_skip_hub_flag_consumed_by_hub_phase(temp_workspace):
    persist_skip_hub_flag()
    out = await hub_phase({})
    assert out["skip_hub_calls"] is True
    assert out["hub_skip_reason"] == "autopoiesis_degraded"
    assert consume_skip_hub_flag() is False


def test_persist_and_consume_skip_hub_flag(temp_workspace):
    persist_skip_hub_flag()
    assert consume_skip_hub_flag() is True
    assert consume_skip_hub_flag() is False
