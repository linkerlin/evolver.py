"""Tests for evolver.gep.a2a_protocol."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from evolver.gep import a2a_protocol as a2a


@respx.mock
async def test_send_hello_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    monkeypatch.setenv("A2A_NODE_ID", "node_123")
    route = respx.post("https://mock.hub/v1/a2a/hello").mock(
        return_value=Response(200, json={"status": "ok"})
    )
    result = await a2a.send_hello()
    assert result["ok"] is True
    assert route.called


@respx.mock
async def test_send_hello_no_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(a2a, "get_hub_url", lambda: None)
    result = await a2a.send_hello()
    assert result["ok"] is False
    assert result["error"] == "no_hub_url"


@respx.mock
async def test_fetch_tasks_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    monkeypatch.setenv("A2A_NODE_ID", "node_123")
    route = respx.post("https://mock.hub/v1/a2a/tasks").mock(
        return_value=Response(200, json={"tasks": [{"task_id": "t1", "title": "Fix bug"}]})
    )
    result = await a2a.fetch_tasks(signals=["log_error"])
    assert result["ok"] is True
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["task_id"] == "t1"
    assert route.called


@respx.mock
async def test_fetch_tasks_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    monkeypatch.setenv("A2A_NODE_ID", "node_123")
    route = respx.post("https://mock.hub/v1/a2a/tasks").mock(side_effect=ConnectionError("nope"))
    result = await a2a.fetch_tasks()
    assert result["ok"] is False
    assert "nope" in result["error"]


@respx.mock
async def test_submit_task_result_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    monkeypatch.setenv("A2A_NODE_ID", "node_123")
    route = respx.post("https://mock.hub/v1/a2a/tasks/t1/result").mock(
        return_value=Response(200, json={"status": "accepted"})
    )
    result = await a2a.submit_task_result("t1", {"outcome": "success"})
    assert result["ok"] is True
    assert route.called


@respx.mock
async def test_consume_hub_events_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    monkeypatch.setenv("A2A_NODE_ID", "node_123")
    route = respx.post("https://mock.hub/v1/a2a/events").mock(
        return_value=Response(200, json={"events": [{"type": "directive", "body": "do X"}]})
    )
    result = await a2a.consume_hub_events()
    assert result["ok"] is True
    assert len(result["events"]) == 1
    assert route.called
