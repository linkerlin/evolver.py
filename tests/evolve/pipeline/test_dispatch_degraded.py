"""Dogfood round-3: degraded cycles dispatch locally instead of idling.

The dispatch phase used to conflate "skip Hub calls" with "skip dispatch" —
a cycle carrying the autopoiesis hub-offline flag (or a preflight-abort
recovery) burned a whole evolution tick as idle even with a matched gene.
Saturation steady-state (no hub_skip_reason) must keep idling.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from evolver.evolve.pipeline.dispatch import dispatch_phase


@pytest.fixture
def _ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    gep = tmp_path / "gep"
    gep.mkdir()
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(ws))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(ws))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(gep))
    return ws


def _ctx(skip_reason: str | None) -> dict[str, Any]:
    return {
        "cycle_id": "c1",
        "run_id": "r1",
        "signals": ["hub_offline", "perf_bottleneck"],
        "selected_gene": {"id": "g1"},
        "mutation": {"id": "m1", "validation": []},
        "skip_hub_calls": True,
        "scan_time_iso": "2026-01-01T00:00:00Z",
        **({"hub_skip_reason": skip_reason} if skip_reason else {}),
    }


def test_degraded_hub_offline_still_dispatches(_ws: Path, capsys: pytest.CaptureFixture) -> None:
    ctx = asyncio.run(dispatch_phase(_ctx("autopoiesis_degraded")))
    assert ctx.get("dispatch_prompt")
    assert "Degraded cycle" in capsys.readouterr().out


def test_preflight_abort_recovery_still_dispatches(_ws: Path) -> None:
    ctx = asyncio.run(dispatch_phase(_ctx("preflight_abort_recovery")))
    assert ctx.get("dispatch_prompt")


def test_saturation_steady_state_stays_idle(_ws: Path, capsys: pytest.CaptureFixture) -> None:
    ctx = asyncio.run(dispatch_phase(_ctx(None)))
    assert "dispatch_prompt" not in ctx
    assert "Idle cycle complete." in capsys.readouterr().out


def test_degraded_without_gene_no_dispatch(_ws: Path, capsys: pytest.CaptureFixture) -> None:
    ctx = _ctx("autopoiesis_degraded")
    ctx["selected_gene"] = None
    result = asyncio.run(dispatch_phase(ctx))
    assert "dispatch_prompt" not in result
    assert "No matching Gene found" in capsys.readouterr().out
