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


@pytest.mark.asyncio
async def test_post_cycle_persists_atp_spawn_instruction(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spawn = "sessions_spawn: work on task t-1 (bounty 5)"
    monkeypatch.setenv("EVOLVER_FF_ENABLE_AUTO_BUYER", "false")
    monkeypatch.setattr(
        "evolver.atp.atp_task_pickup.pick_one",
        AsyncMock(return_value=spawn),
    )
    ctx = await run_post_cycle_hooks({"signals": ["log_error"]})
    assert ctx["atp_spawn_instruction"] == spawn
    path = temp_workspace / "memory" / "evolution" / "atp_spawn_instruction.json"
    assert path.exists()
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["instruction"] == spawn


@pytest.mark.asyncio
async def test_post_cycle_applies_gene_lifecycle(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RSI P1-5: post_cycle derives lifecycle verdicts from the event lineage."""
    from evolver.gep import gene_lifecycle as gl
    from evolver.gep.asset_store import append_event_jsonl

    monkeypatch.setattr("evolver.atp.atp_task_pickup.pick_one", AsyncMock(return_value=None))
    monkeypatch.setattr("evolver.gep.issue_reporter.report_recurring_failures", lambda **_: [])

    events: list[dict[str, Any]] = []
    for i in range(3):
        events.append(
            {
                "id": f"evt_land_{i}",
                "outcome": {"status": "success"},
                "mutation": {"landed_gene_ids": ["gene_dead"]},
                "signals": ["log_error"],
            }
        )
        events.append(
            {"id": f"evt_fail_{i}", "outcome": {"status": "failed"}, "signals": ["log_error"]}
        )
    events.extend(
        {"id": f"evt_ok_{i}", "outcome": {"status": "success"}, "signals": ["hub_offline"]}
        for i in range(5)
    )
    for event in events:
        append_event_jsonl(event)

    ctx = await run_post_cycle_hooks({"signals": ["log_error"]})
    assert ctx["gene_lifecycle"]["transitions"][0]["to_status"] == "under_review"
    assert gl.load_lifecycle()["gene_dead"].status == "under_review"

    # Idempotent: a second pass with the same lineage applies nothing new.
    again = await run_post_cycle_hooks({"signals": ["log_error"]})
    assert "gene_lifecycle" not in again


async def test_post_cycle_rotates_evidence_dirs(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round-59: evidence rotation runs in the PER-CYCLE path — the daemon
    loop's cleanup was the only caller, and the running daemon predates the
    rotation, so single-cycle runs never rotated anything (dead wiring)."""
    import time as _time

    monkeypatch.setattr("evolver.atp.atp_task_pickup.pick_one", AsyncMock(return_value=None))
    monkeypatch.setattr("evolver.gep.issue_reporter.report_recurring_failures", lambda **_: [])
    evidence = temp_workspace / ".evolver" / "gep" / "evidence"
    for i in range(12):
        run_dir = evidence / f"run_{i:02d}"
        run_dir.mkdir(parents=True)
        (run_dir / "evt.json").write_text("{}", encoding="utf-8")
        stamp = _time.time() + i
        import os

        os.utime(run_dir, (stamp, stamp))

    ctx = await run_post_cycle_hooks({"signals": ["log_error"]})
    remaining = sorted(p.name for p in evidence.iterdir())
    assert len(remaining) == 10, f"rotation keeps CLEANUP_MAX_FILES: {remaining}"
    assert remaining[-1] == "run_11", "newest kept"
    assert ctx["evidence_rotation"]["removed"] == 2
