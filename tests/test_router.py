"""Tests for evolver.gep.router."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from evolver.gep.discovery import add_peer
from evolver.gep.router import route_message


class TestRouteMessage:
    async def test_local_delivery(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("A2A_NODE_ID", "self")
        result = await route_message("self", {"type": "ping"})
        assert result["ok"] is True
        assert result.get("local") is True

    @respx.mock
    async def test_remote_forward(self) -> None:
        add_peer("remote_1", "http://remote:8080")
        route = respx.post("http://remote:8080/v1/a2a/receive").mock(
            return_value=Response(200, json={"ack": True})
        )
        result = await route_message("remote_1", {"type": "ping"})
        assert result["ok"] is True
        assert result.get("remote") is True
        assert route.called

    async def test_no_route(self) -> None:
        result = await route_message("unknown_node", {"type": "ping"})
        assert result["ok"] is False
        assert "No route" in result["error"]
