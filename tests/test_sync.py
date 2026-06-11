"""Tests for evolver.gep.sync."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from evolver.gep import sync


@respx.mock
async def test_sync_all_no_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    route_tasks = respx.post("https://mock.hub/v1/a2a/tasks").mock(
        return_value=Response(200, json={"tasks": []})
    )
    route_events = respx.post("https://mock.hub/v1/a2a/events").mock(
        return_value=Response(200, json={"events": []})
    )
    result = await sync.sync_all(dry_run=True)
    assert result["ok"] is True
    assert result["count"] == 0


@respx.mock
async def test_sync_all_tasks_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    respx.post("https://mock.hub/v1/a2a/tasks").mock(
        return_value=Response(200, json={"tasks": [{"task_id": "t1", "title": "Fix bug"}]})
    )
    respx.post("https://mock.hub/v1/a2a/events").mock(
        return_value=Response(200, json={"events": []})
    )
    result = await sync.sync_all(dry_run=False)
    assert result["ok"] is True
    assert any(i.get("id") == "t1" for i in result["installed"])


@respx.mock
async def test_sync_all_events_with_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    respx.post("https://mock.hub/v1/a2a/tasks").mock(return_value=Response(200, json={"tasks": []}))
    respx.post("https://mock.hub/v1/a2a/events").mock(
        return_value=Response(200, json={"events": [{"asset_id": "raw:g1", "body": "install g1"}]})
    )
    respx.post("https://mock.hub/v1/a2a/assets").mock(
        return_value=Response(
            200, json={"asset": {"type": "Gene", "id": "g1", "category": "repair"}}
        )
    )
    result = await sync.sync_all(dry_run=False)
    assert result["ok"] is True
    assert any(i.get("id") == "g1" for i in result["installed"])
