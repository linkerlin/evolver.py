"""Tests for evolver.evolve.post_cycle."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from evolver.evolve.post_cycle import run_post_cycle_hooks


@pytest.mark.asyncio
async def test_post_cycle_skips_without_signals() -> None:
    ctx: dict[str, Any] = {"signals": []}
    result = await run_post_cycle_hooks(ctx)
    assert "atp_auto_buyer" not in result


@pytest.mark.asyncio
async def test_post_cycle_runs_auto_buyer_when_enabled(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evolver.atp import auto_buyer

    monkeypatch.setenv("EVOLVER_FF_ENABLE_AUTO_BUYER", "true")
    monkeypatch.setenv("EVOLVER_ATP_AUTOBUY", "1")
    monkeypatch.setattr(auto_buyer, "get_memory_dir", lambda: temp_workspace)
    mock_tick = AsyncMock(return_value={"ok": True, "placed": 1, "orders": []})
    monkeypatch.setattr(auto_buyer, "run_tick", mock_tick)
    monkeypatch.setattr(
        "evolver.atp.atp_task_pickup.pick_one",
        AsyncMock(return_value=None),
    )

    ctx = {"signals": ["TypeError in module"]}
    result = await run_post_cycle_hooks(ctx)
    assert result["atp_auto_buyer"]["placed"] == 1
    mock_tick.assert_called_once_with(["TypeError in module"])


@pytest.mark.asyncio
async def test_post_cycle_issue_reporter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "evolver.atp.atp_task_pickup.pick_one",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "evolver.gep.issue_reporter.report_recurring_failures",
        lambda **_: ["https://github.com/o/r/issues/1"],
    )
    monkeypatch.setattr(
        "evolver.gep.memory_graph.read_all",
        lambda limit=500: [{"type": "attempt", "timestamp": 1, "outcome": "fail"}],
    )
    ctx = {"signals": ["log_error"]}
    result = await run_post_cycle_hooks(ctx)
    assert result["issue_reporter_urls"] == ["https://github.com/o/r/issues/1"]


@pytest.mark.asyncio
async def test_post_cycle_task_pickup_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "evolver.atp.atp_task_pickup.pick_one",
        AsyncMock(return_value="# ATP Task spawn\n"),
    )
    ctx = {"signals": ["log_error"]}
    result = await run_post_cycle_hooks(ctx)
    assert "atp_spawn_instruction" in result
