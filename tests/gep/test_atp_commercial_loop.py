"""End-to-end ATP commercial loop with mocked Hub calls."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from evolver.atp import auto_buyer, auto_deliver, heartbeat_signals_handler
from evolver.evolve.post_cycle import run_post_cycle_hooks


@pytest.mark.asyncio
async def test_commercial_loop_buy_deliver_heartbeat(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Buyer places order → deliver submits proof → heartbeat confirms delivery."""
    monkeypatch.setenv("EVOLVER_ATP_AUTOBUY", "1")
    monkeypatch.setenv("EVOLVER_FF_ENABLE_AUTO_BUYER", "true")
    monkeypatch.setattr(auto_buyer, "get_memory_dir", lambda: temp_workspace)

    orders: list[str] = []

    async def fake_place(*_a: Any, **_k: Any) -> dict[str, Any]:
        orders.append("placed")
        return {"ok": True, "data": {"order_id": "ord_loop_1"}}

    async def fake_submit(order_id: str, proof: str, asset_id: str | None = None) -> dict[str, Any]:
        orders.append(f"deliver:{order_id}")
        return {"ok": True}

    monkeypatch.setattr(auto_buyer, "place_order", fake_place)
    monkeypatch.setattr(auto_deliver, "submit_delivery", fake_submit)
    monkeypatch.setattr(heartbeat_signals_handler, "submit_delivery", fake_submit)
    monkeypatch.setattr(
        "evolver.atp.atp_task_pickup.pick_one",
        AsyncMock(return_value=None),
    )

    auto_buyer.set_consent(True)
    buy = await auto_buyer.run_tick(["TypeError in tests"])
    assert buy.get("placed", 0) >= 1
    assert orders == ["placed"]

    ad = auto_deliver.AutoDeliver()
    await ad._handle_task(
        {
            "atp_order_id": "ord_loop_claim",
            "status": "claimed",
            "task_id": "t1",
            "title": "review",
        }
    )
    assert any(o.startswith("deliver:ord_loop_claim") for o in orders)

    heartbeat_signals_handler._LAST_RUN_AT = 0.0
    hb = await heartbeat_signals_handler.handle_signals(
        {
            "pending_deliveries": [
                {"order_id": "ord_hb_final", "result_asset_id": "asset_final"},
            ],
        }
    )
    assert hb.get("deliveries") == 1
    assert "deliver:ord_hb_final" in orders


@pytest.mark.asyncio
async def test_post_cycle_wires_into_pipeline(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOLVER_FF_ENABLE_AUTO_BUYER", "true")
    monkeypatch.setenv("EVOLVER_ATP_AUTOBUY", "1")
    monkeypatch.setattr(auto_buyer, "get_memory_dir", lambda: temp_workspace)
    monkeypatch.setattr(auto_buyer, "place_order", AsyncMock(return_value={"ok": True, "data": {}}))
    monkeypatch.setattr(
        "evolver.atp.atp_task_pickup.pick_one",
        AsyncMock(return_value="# spawn"),
    )

    ctx = await run_post_cycle_hooks({"signals": ["pytest failed"]})
    assert "atp_auto_buyer" in ctx
    assert ctx.get("atp_spawn_instruction") == "# spawn"
