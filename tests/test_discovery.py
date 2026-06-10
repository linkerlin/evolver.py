"""Tests for evolver.gep.discovery."""

from __future__ import annotations

from pathlib import Path

import pytest
import respx
from httpx import Response

from evolver.gep.discovery import (
    add_peer,
    discover_peers,
    get_peer_endpoint,
    list_peers,
    load_peers,
    remove_peer,
    save_peers,
)


@pytest.fixture(autouse=True)
def _clear_peers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evolver"))
    # Clear in-memory registry
    import evolver.gep.discovery as disc
    disc._PEERS.clear()


class TestPeerRegistry:
    def test_add_and_list(self) -> None:
        add_peer("node_a", "http://a:8080", {"region": "us"})
        peers = list_peers()
        assert len(peers) == 1
        assert peers[0]["node_id"] == "node_a"

    def test_remove(self) -> None:
        add_peer("node_a", "http://a:8080")
        assert remove_peer("node_a") is True
        assert remove_peer("node_a") is False

    def test_get_endpoint(self) -> None:
        add_peer("node_b", "http://b:9000")
        assert get_peer_endpoint("node_b") == "http://b:9000"
        assert get_peer_endpoint("node_x") is None

    def test_stale_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import time

        add_peer("fresh", "http://f:1")
        add_peer("stale", "http://s:1")
        # Artificially age stale peer
        import evolver.gep.discovery as disc

        disc._PEERS["stale"]["last_seen"] = time.time() - 400
        peers = list_peers()
        ids = {p["node_id"] for p in peers}
        assert "fresh" in ids
        assert "stale" not in ids


class TestPersistence:
    def test_round_trip(self) -> None:
        add_peer("node_c", "http://c:1")
        save_peers()
        disc = load_peers()
        assert "node_c" in disc


class TestDiscoverPeers:
    @respx.mock
    async def test_success(self) -> None:
        respx.get("https://evomap.ai/v1/a2a/peers").mock(
            return_value=Response(
                200,
                json={"peers": [{"node_id": "p1", "endpoint": "http://p1:8080"}]},
            )
        )
        result = await discover_peers()
        assert result["ok"] is True
        assert len(result["peers"]) == 1
        assert get_peer_endpoint("p1") == "http://p1:8080"

    @respx.mock
    async def test_hub_error(self) -> None:
        respx.get("https://evomap.ai/v1/a2a/peers").mock(return_value=Response(500))
        result = await discover_peers()
        assert result["ok"] is False
