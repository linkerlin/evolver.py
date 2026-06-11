"""Integration tests for ATP heartbeat signal handling."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from evolver.atp import auto_buyer, heartbeat_signals_handler
from evolver.gep.asset_store import atomic_write_json, pending_signals_path


@pytest.mark.asyncio
async def test_collect_heartbeat_signals_merges_sources(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEP_ASSETS_DIR", str(temp_workspace / "gep"))
    atomic_write_json(pending_signals_path(), {"signals": ["pending pytest failure"]})

    body = {
        "signals": ["TypeError in module"],
        "pending_atp_tasks": [{"question": "How to fix imports?"}],
    }
    collected = heartbeat_signals_handler.collect_heartbeat_signals(body)
    assert "TypeError in module" in collected
    assert "How to fix imports?" in collected
    assert "pending pytest failure" in collected


@pytest.mark.asyncio
async def test_handle_signals_runs_auto_buyer(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOLVER_ATP_AUTOBUY", "1")
    monkeypatch.setattr(auto_buyer, "get_memory_dir", lambda: temp_workspace)
    mock_tick = AsyncMock(return_value={"ok": True, "placed": 1, "orders": []})
    monkeypatch.setattr(auto_buyer, "run_tick", mock_tick)

    heartbeat_signals_handler._LAST_RUN_AT = 0.0
    result = await heartbeat_signals_handler.handle_signals(
        {"signals": ["pytest failed"], "pending_deliveries": []}
    )
    assert result["ok"] is True
    mock_tick.assert_called_once()


@pytest.mark.asyncio
async def test_handle_signals_submits_deliveries(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_submit = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(heartbeat_signals_handler, "submit_delivery", mock_submit)

    heartbeat_signals_handler._LAST_RUN_AT = 0.0
    result = await heartbeat_signals_handler.handle_signals(
        {
            "pending_deliveries": [
                {"order_id": "ord_1", "result_asset_id": "asset_1"},
            ]
        }
    )
    assert result["deliveries"] == 1
    mock_submit.assert_called_once()


@pytest.mark.asyncio
async def test_lifecycle_heartbeat_invokes_signals(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx
    import respx
    from evolver.proxy.lifecycle.manager import LifecycleManager
    from evolver.proxy.mailbox.store import MailboxStore

    monkeypatch.setenv("A2A_HUB_URL", "https://hub.test")
    store = MailboxStore(temp_workspace / "mailbox")
    manager = LifecycleManager(store=store)
    manager._state.node_id = "node_test"

    mock_handle = AsyncMock(return_value={"ok": True, "deliveries": 0})
    monkeypatch.setattr(
        "evolver.atp.heartbeat_signals_handler.handle_signals",
        mock_handle,
    )

    with respx.mock:
        respx.post("https://hub.test/v1/a2a/heartbeat").mock(
            return_value=httpx.Response(200, json={"pending_deliveries": []})
        )
        result = await manager.heartbeat()

    assert result["ok"] is True
    assert "atp_signals" in result
    mock_handle.assert_called_once()
