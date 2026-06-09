"""Tests for evolver.atp.client."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from evolver.atp.client import buy, complete_task, list_orders, verify_delivery


class TestBuy:
    @respx.mock
    async def test_success(self) -> None:
        route = respx.post("https://evomap.ai/v1/atp/orders").mock(
            return_value=Response(200, json={"id": "ord_123", "status": "pending"})
        )
        result = await buy(skill_id="skill_abc", quantity=2)
        assert result["ok"] is True
        assert result["order"]["id"] == "ord_123"
        sent = route.calls[0].request.content
        assert b"skill_abc" in sent
        assert b"2" in sent

    @respx.mock
    async def test_hub_error(self) -> None:
        respx.post("https://evomap.ai/v1/atp/orders").mock(return_value=Response(500))
        result = await buy(skill_id="skill_abc")
        assert result["ok"] is False


class TestListOrders:
    @respx.mock
    async def test_success(self) -> None:
        respx.get("https://evomap.ai/v1/atp/orders?limit=10").mock(
            return_value=Response(200, json={"orders": [{"id": "o1"}, {"id": "o2"}]})
        )
        result = await list_orders(limit=10)
        assert result["ok"] is True
        assert len(result["orders"]) == 2

    @respx.mock
    async def test_with_status_filter(self) -> None:
        route = respx.get("https://evomap.ai/v1/atp/orders").mock(
            return_value=Response(200, json={"orders": []})
        )
        await list_orders(status="completed", limit=5)
        req = route.calls[0].request
        assert "status=completed" in str(req.url)
        assert "limit=5" in str(req.url)


class TestVerifyDelivery:
    @respx.mock
    async def test_approve(self) -> None:
        route = respx.post("https://evomap.ai/v1/atp/orders/ord_1/verify").mock(
            return_value=Response(200, json={"status": "verified"})
        )
        result = await verify_delivery("ord_1", approval=True)
        assert result["ok"] is True
        assert b"approved\"" in route.calls[0].request.content

    @respx.mock
    async def test_reject(self) -> None:
        route = respx.post("https://evomap.ai/v1/atp/orders/ord_1/verify").mock(
            return_value=Response(200, json={"status": "rejected"})
        )
        result = await verify_delivery("ord_1", approval=False)
        assert result["ok"] is True
        assert b"approved\":false" in route.calls[0].request.content


class TestCompleteTask:
    @respx.mock
    async def test_success(self) -> None:
        route = respx.post("https://evomap.ai/v1/atp/tasks/task_1/complete").mock(
            return_value=Response(200, json={"status": "completed"})
        )
        result = await complete_task("task_1", {"output": "done"})
        assert result["ok"] is True
        assert b"done" in route.calls[0].request.content

    @respx.mock
    async def test_hub_error(self) -> None:
        respx.post("https://evomap.ai/v1/atp/tasks/task_1/complete").mock(return_value=Response(500))
        result = await complete_task("task_1")
        assert result["ok"] is False
