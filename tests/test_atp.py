"""Tests for ATP marketplace modules."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from evolver.atp import (
    auto_buyer,
    auto_deliver,
    cli_autobuy_prompt,
    consumer_agent,
    heartbeat_signals_handler,
    hub_client,
    merchant_agent,
    protocol,
    question_composer,
    service_helper,
)
from evolver.atp.atp_task_pickup import pick_one, forget


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
    result = await heartbeat_signals_handler.handle_signals({})
    # Should not raise
    assert True


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
