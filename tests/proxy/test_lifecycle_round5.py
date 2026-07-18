"""Sprint 14.7 — heartbeat Round-5 resilience (unknown_node backoff)."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from evolver.proxy.lifecycle.manager import (
    HELLO_RECOVERY_DELAY_MS,
    UNKNOWN_NODE_BACKOFF_MS,
    LifecycleManager,
)


class _FakeStore:
    def __init__(self) -> None:
        self._state: dict[str, Any] = {}

    def get_state(self, key: str, default: Any = None) -> Any:
        return self._state.get(key, default)

    def set_state(self, key: str, value: Any) -> None:
        self._state[key] = value

    def count_pending(self, direction: str = "outbound") -> int:
        return 0


@pytest.fixture
def manager(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> LifecycleManager:
    monkeypatch.setenv("A2A_HUB_URL", "https://hub.round5.test")
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evomap"))
    store = _FakeStore()
    mgr = LifecycleManager(store=store, version="1.0.0")
    mgr._state.node_id = "node_deadbeefcafe"
    mgr._state.node_secret = "a" * 64
    return mgr


def _mock_client(body: dict[str, Any], status: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value=body)
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=response)
    return client


class TestUnknownNodeBackoff:
    @pytest.mark.asyncio
    async def test_threshold_installs_absolute_deadline(
        self, manager: LifecycleManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _mock_client({"status": "unknown_node"})
        monkeypatch.setattr(
            "evolver.proxy.lifecycle.manager.httpx.AsyncClient",
            lambda **_k: client,
        )
        # hello re-register also mocked
        manager.hello = AsyncMock(return_value={"ok": True})  # type: ignore[method-assign]

        before = time.time() * 1000
        manager._state.last_heartbeat_attempt_at = None
        await manager.heartbeat()
        manager._state.last_heartbeat_attempt_at = None  # bypass rate limit
        await manager.heartbeat()
        stats = manager.get_heartbeat_stats()
        assert stats["unknownNodeBackoffUntil"] > before + 7 * 60_000
        assert stats["unknownNodeBackoffActive"] is True
        assert stats["unknownNodeStreak"] >= 2

    @pytest.mark.asyncio
    async def test_poke_refused_while_deadline_active(self, manager: LifecycleManager) -> None:
        now = time.time() * 1000
        manager._state.unknown_node_backoff_until_ms = now + 4 * 60_000
        manager._state.heartbeat_failures = 3
        result = manager.poke_heartbeat_loop()
        assert result is False
        # Failure counter untouched
        assert manager._state.heartbeat_failures == 3
        assert manager._state.unknown_node_backoff_until_ms > now

    @pytest.mark.asyncio
    async def test_heartbeat_skips_during_backoff(self, manager: LifecycleManager) -> None:
        manager._state.unknown_node_backoff_until_ms = time.time() * 1000 + 60_000
        res = await manager.heartbeat()
        assert res["ok"] is False
        assert res["error"] == "unknown_node_backoff"

    @pytest.mark.asyncio
    async def test_hello_recovery_arms_pending_delay(
        self, manager: LifecycleManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _mock_client({"status": "unknown_node"})
        monkeypatch.setattr(
            "evolver.proxy.lifecycle.manager.httpx.AsyncClient",
            lambda **_k: client,
        )
        manager.hello = AsyncMock(return_value={"ok": True})  # type: ignore[method-assign]
        assert manager._state.pending_reschedule_delay_ms == 0
        manager._state.last_heartbeat_attempt_at = None
        await manager.heartbeat()
        # Below threshold (streak=1) still arms hello-recovery delay
        assert manager._state.pending_reschedule_delay_ms >= HELLO_RECOVERY_DELAY_MS

    @pytest.mark.asyncio
    async def test_success_clears_unknown_node(
        self, manager: LifecycleManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager._state.unknown_node_streak = 5
        # Deadline must be in the past so heartbeat is not short-circuited.
        manager._state.unknown_node_backoff_until_ms = time.time() * 1000 - 1
        client = _mock_client({"status": "ok"})
        monkeypatch.setattr(
            "evolver.proxy.lifecycle.manager.httpx.AsyncClient",
            lambda **_k: client,
        )
        monkeypatch.setattr(
            "evolver.atp.heartbeat_signals_handler.handle_signals",
            AsyncMock(return_value={}),
        )
        # Bypass rate limit for test
        manager._state.last_heartbeat_attempt_at = None
        res = await manager.heartbeat()
        assert res.get("ok") is True, res
        assert manager._state.unknown_node_streak == 0
        assert manager._state.unknown_node_backoff_until_ms == 0.0


class TestHeartbeatStats:
    def test_self_driving_poll_fields(self, manager: LifecycleManager) -> None:
        manager.enable_self_driving_poll(enabled=True, backoff_ms=1500)
        stats = manager.get_heartbeat_stats()
        assert stats["selfDrivingPollEnabled"] is True
        assert stats["selfDrivingPollBackoffMs"] == 1500
        assert "unknownNodeBackoffUntil" in stats
        assert stats["connection_status"] in (
            "unregistered",
            "connected",
            "idle",
        )


class TestConstants:
    def test_backoff_window(self) -> None:
        assert UNKNOWN_NODE_BACKOFF_MS >= 7 * 60 * 1000
