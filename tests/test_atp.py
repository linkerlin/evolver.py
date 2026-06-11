"""Tests for ATP marketplace modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from evolver.atp import (
    auto_buyer,
    auto_deliver,
    cli_autobuy_prompt,
    consumer_agent,
    heartbeat_signals_handler,
    merchant_agent,
    protocol,
    question_composer,
)
from evolver.atp.atp_task_pickup import pick_one

# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


def test_order_status_enum() -> None:
    assert protocol.OrderStatus.pending.value == "pending"
    assert protocol.OrderStatus.settled.value == "settled"


def test_pydantic_models() -> None:
    o = protocol.Order(order_id="o1", service_id="s1", buyer_id="b1", budget=10.0)
    assert o.status == protocol.OrderStatus.pending

    with pytest.raises(ValueError):
        protocol.Order(order_id="o1", service_id="s1", buyer_id="b1", budget=-1)


# ---------------------------------------------------------------------------
# Question composer
# ---------------------------------------------------------------------------


def test_compose_basic() -> None:
    q = question_composer.compose(["debugging"], "TypeError on line 42")
    assert "TypeError" in q or "Debug" in q or "debug" in q.lower()
    assert len(q) <= 240


def test_compose_fallback() -> None:
    q = question_composer.compose([], "something weird")
    assert len(q) <= 240


def test_detect_capability_gaps() -> None:
    gaps = auto_buyer.detect_capability_gaps(["TypeError in module", "pytest failed"])
    caps = {g["capability"] for g in gaps}
    assert "debugging" in caps
    assert "testing" in caps


def test_detect_capability_gaps_empty() -> None:
    assert auto_buyer.detect_capability_gaps([]) == []


# ---------------------------------------------------------------------------
# Auto buyer
# ---------------------------------------------------------------------------


def test_consent_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_ATP_AUTOBUY", "1")
    c = auto_buyer.get_consent()
    assert c is not None
    assert c["enabled"] is True


def test_consent_ack_file(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOLVER_ATP_AUTOBUY", raising=False)
    monkeypatch.setattr(auto_buyer, "get_memory_dir", lambda: temp_workspace)
    auto_buyer.set_consent(True)
    c = auto_buyer.get_consent()
    assert c is not None
    assert c["enabled"] is True


def test_effective_cap_cold_start(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOLVER_ATP_AUTOBUY", raising=False)
    monkeypatch.setattr(auto_buyer, "get_memory_dir", lambda: temp_workspace)
    auto_buyer.set_consent(True)
    cap = auto_buyer._effective_cap()
    assert cap > 0


@pytest.mark.asyncio
async def test_consider_order_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOLVER_ATP_AUTOBUY", raising=False)
    monkeypatch.setattr(auto_buyer, "get_memory_dir", lambda: Path("/tmp/nonexistent"))
    result = await auto_buyer.consider_order(["debugging"])
    assert result["ok"] is False
    assert "disabled" in result["error"]


@pytest.mark.asyncio
async def test_consider_order_success(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOLVER_ATP_AUTOBUY", "1")
    monkeypatch.setattr(auto_buyer, "get_memory_dir", lambda: temp_workspace)
    mock_place = AsyncMock(return_value={"ok": True, "data": {"order_id": "ord_1"}})
    monkeypatch.setattr(auto_buyer, "place_order", mock_place)

    result = await auto_buyer.consider_order(["debugging"], signal="TypeError")
    assert result["ok"] is True
    mock_place.assert_called_once()
    ledger = auto_buyer._read_ledger()
    assert ledger["spent"] > 0


@pytest.mark.asyncio
async def test_consider_order_dedup_24h(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOLVER_ATP_AUTOBUY", "1")
    monkeypatch.setattr(auto_buyer, "get_memory_dir", lambda: temp_workspace)
    mock_place = AsyncMock(return_value={"ok": True, "data": {"order_id": "ord_1"}})
    monkeypatch.setattr(auto_buyer, "place_order", mock_place)

    first = await auto_buyer.consider_order(["debugging"], signal="same error")
    assert first["ok"] is True
    second = await auto_buyer.consider_order(["debugging"], signal="same error")
    assert second["ok"] is False
    assert second["error"] == "dedup_24h"
    assert mock_place.call_count == 1


@pytest.mark.asyncio
async def test_run_tick_places_orders(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOLVER_ATP_AUTOBUY", "1")
    monkeypatch.setattr(auto_buyer, "get_memory_dir", lambda: temp_workspace)
    mock_place = AsyncMock(return_value={"ok": True, "data": {"order_id": "ord_tick"}})
    monkeypatch.setattr(auto_buyer, "place_order", mock_place)

    result = await auto_buyer.run_tick(["unexpected TypeError in handler"])
    assert result["ok"] is True
    assert result["placed"] == 1
    assert len(result["orders"]) == 1


@pytest.mark.asyncio
async def test_run_tick_no_gaps(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_ATP_AUTOBUY", "1")
    monkeypatch.setattr(auto_buyer, "get_memory_dir", lambda: temp_workspace)
    result = await auto_buyer.run_tick(["everything is fine"])
    assert result["ok"] is True
    assert result["orders"] == []


# ---------------------------------------------------------------------------
# Auto deliver
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_deliver_lifecycle() -> None:
    ad = auto_deliver.AutoDeliver(poll_interval_s=1)
    ad.start()
    await __import__("asyncio").sleep(0.01)
    assert ad.is_started() is True
    ad.stop()
    assert ad.is_started() is False


@pytest.mark.asyncio
async def test_auto_deliver_handle_task(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auto_deliver, "get_memory_dir", lambda: temp_workspace)
    mock_submit = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(auto_deliver, "submit_delivery", mock_submit)

    ad = auto_deliver.AutoDeliver()
    await ad._handle_task(
        {
            "atp_order_id": "ord_99",
            "status": "completed",
            "result_asset_id": "asset_99",
            "task_id": "task_99",
        }
    )
    mock_submit.assert_called_once()
    assert auto_deliver._already_submitted("ord_99") is True


@pytest.mark.asyncio
async def test_auto_deliver_skips_duplicate(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auto_deliver, "get_memory_dir", lambda: temp_workspace)
    auto_deliver._mark_submitted("ord_dup", success=True)
    mock_submit = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(auto_deliver, "submit_delivery", mock_submit)

    ad = auto_deliver.AutoDeliver()
    await ad._handle_task(
        {
            "atp_order_id": "ord_dup",
            "status": "completed",
            "result_asset_id": "asset_dup",
            "task_id": "task_dup",
        }
    )
    mock_submit.assert_not_called()


@pytest.mark.asyncio
async def test_auto_deliver_claimed_via_default_handler(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auto_deliver, "get_memory_dir", lambda: temp_workspace)
    mock_submit = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(auto_deliver, "submit_delivery", mock_submit)

    ad = auto_deliver.AutoDeliver()
    await ad._handle_task(
        {
            "atp_order_id": "ord_claim",
            "status": "claimed",
            "task_id": "task_claim",
            "title": "Code review request",
        }
    )
    mock_submit.assert_called_once()
    args = mock_submit.call_args[0]
    assert args[0] == "ord_claim"
    assert auto_deliver._already_submitted("ord_claim") is True


# ---------------------------------------------------------------------------
# Consumer agent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_order_and_wait_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_place(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "data": {"order_id": "ord_123"}}

    async def fake_check(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "data": {"status": "pending"}}

    monkeypatch.setattr(consumer_agent, "order_service", fake_place)
    monkeypatch.setattr(consumer_agent, "check_order", fake_check)

    result = await consumer_agent.order_and_wait("svc1", 5.0, poll_interval_s=0.05, timeout_s=0.2)
    assert result["ok"] is False
    assert "timeout" in result["error"]


# ---------------------------------------------------------------------------
# Merchant agent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merchant_agent_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(merchant_agent, "send_hello", AsyncMock(return_value={"ok": True}))
    monkeypatch.setattr(merchant_agent, "publish", AsyncMock(return_value={"ok": True}))

    async def on_order(task: dict[str, Any]) -> dict[str, Any]:
        return {"proof": "done", "result_asset_id": "asset_1"}

    agent = merchant_agent.MerchantAgent(
        services=[{"title": "Test", "description": "d", "capabilities": ["c"]}],
        on_order=on_order,
        poll_interval_s=0.1,
    )
    await agent.start()
    await __import__("asyncio").sleep(0.05)
    assert agent.is_running() is True
    agent.stop()


# ---------------------------------------------------------------------------
# Heartbeat signals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_signals_no_crash() -> None:
    heartbeat_signals_handler._LAST_RUN_AT = 0.0
    result = await heartbeat_signals_handler.handle_signals({})
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# Task pickup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pick_one_no_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "evolver.atp.atp_task_pickup.list_my_tasks",
        AsyncMock(return_value={"ok": True, "data": {"tasks": []}}),
    )
    result = await pick_one()
    assert result is None


# ---------------------------------------------------------------------------
# CLI autobuy prompt
# ---------------------------------------------------------------------------


def test_classify_non_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli_autobuy_prompt.classify() == "non_tty"


def test_classify_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setenv("EVOLVER_ATP_AUTOBUY", "1")
    assert cli_autobuy_prompt.classify() == "env_set"
