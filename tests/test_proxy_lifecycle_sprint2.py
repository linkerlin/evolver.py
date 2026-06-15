"""Tests for Sprint 2 Hub lifecycle resilience features."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from evolver.proxy.lifecycle.manager import (
    ERROR_BACKOFF_THRESHOLD,
    MIN_HEARTBEAT_INTERVAL_MS,
    SECRET_STALE_TTL_S,
    LifecycleManager,
)


class FakeStore:
    """In-memory store for testing."""

    def __init__(self) -> None:
        self._state: dict[str, Any] = {}

    def get_state(self, key: str) -> Any:
        return self._state.get(key)

    def set_state(self, key: str, value: Any) -> None:
        self._state[key] = value

    def count_pending(self, direction: str = "outbound") -> int:  # noqa: ARG002
        return 0


@pytest.fixture()
def manager() -> LifecycleManager:
    return LifecycleManager(store=FakeStore())


# ---------------------------------------------------------------------------
# L1: ERROR_BACKOFF
# ---------------------------------------------------------------------------


class TestErrorBackoff:
    def test_enters_backoff_after_threshold(self, manager: LifecycleManager) -> None:
        manager._state.reauth_failures = ERROR_BACKOFF_THRESHOLD
        manager._enter_error_backoff()
        assert manager._state.in_error_backoff is True
        assert manager._state.error_backoff_until is not None

    def test_no_backoff_below_threshold(self, manager: LifecycleManager) -> None:
        manager._state.reauth_failures = 1
        manager._enter_error_backoff()
        assert manager._state.in_error_backoff is False

    def test_is_in_backoff_when_active(self, manager: LifecycleManager) -> None:
        manager._state.in_error_backoff = True
        manager._state.error_backoff_until = time.time() + 300
        assert manager._is_in_error_backoff() is True

    def test_exits_backoff_after_timeout(self, manager: LifecycleManager) -> None:
        manager._state.in_error_backoff = True
        manager._state.error_backoff_until = time.time() - 1  # expired
        assert manager._is_in_error_backoff() is False
        assert manager._state.in_error_backoff is False

    def test_heartbeat_blocked_during_backoff(self, manager: LifecycleManager) -> None:
        manager._state.in_error_backoff = True
        manager._state.error_backoff_until = time.time() + 300
        result = asyncio.run(manager.heartbeat())
        assert result["error"] == "error_backoff"


# ---------------------------------------------------------------------------
# L2: TLS enforcement
# ---------------------------------------------------------------------------


class TestTlsEnforcement:
    def test_https_accepted(self) -> None:
        result = LifecycleManager.enforce_tls("https://evomap.ai")
        assert result["ok"] is True
        assert result["warnings"] == []

    def test_http_warning_in_dev(self) -> None:
        result = LifecycleManager.enforce_tls("http://localhost:8080")
        assert result["ok"] is True
        assert len(result["warnings"]) > 0

    def test_http_rejected_in_production(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_ENV", "production")
        result = LifecycleManager.enforce_tls("http://evomap.ai")
        assert result["ok"] is False

    def test_protocol_less_url_warns(self) -> None:
        result = LifecycleManager.enforce_tls("evomap.ai")
        assert result["ok"] is True
        assert len(result["warnings"]) > 0


# ---------------------------------------------------------------------------
# L3: Offline permit
# ---------------------------------------------------------------------------


class TestOfflinePermit:
    def test_acquire_and_release(self, manager: LifecycleManager) -> None:
        manager._state.node_id = "node-1"
        assert manager.acquire_offline_permit() is True
        assert manager.acquire_offline_permit() is True  # re-acquire OK
        manager.release_offline_permit()

    def test_contention(self) -> None:
        store = FakeStore()
        m1 = LifecycleManager(store=store)
        m2 = LifecycleManager(store=store)
        m1._state.node_id = "node-1"
        m2._state.node_id = "node-2"
        assert m1.acquire_offline_permit() is True
        assert m2.acquire_offline_permit() is False  # held by node-1


# ---------------------------------------------------------------------------
# L4: Stale secret
# ---------------------------------------------------------------------------


class TestStaleSecret:
    def test_fresh_secret_not_stale(self, manager: LifecycleManager) -> None:
        manager._state.secret_set_at = time.time()
        assert manager.is_secret_stale() is False

    def test_old_secret_is_stale(self, manager: LifecycleManager) -> None:
        manager._state.secret_set_at = time.time() - SECRET_STALE_TTL_S - 1
        assert manager.is_secret_stale() is True

    def test_never_set_is_stale(self, manager: LifecycleManager) -> None:
        manager._state.secret_set_at = None
        assert manager.is_secret_stale() is True


# ---------------------------------------------------------------------------
# L5: Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimit:
    def test_first_call_allowed(self, manager: LifecycleManager) -> None:
        manager._state.last_heartbeat_attempt_at = None
        assert manager._check_rate_limit() is True

    def test_burst_blocked(self, manager: LifecycleManager) -> None:
        manager._state.last_heartbeat_attempt_at = time.time()
        assert manager._check_rate_limit() is False

    def test_after_interval_allowed(self, manager: LifecycleManager) -> None:
        manager._state.last_heartbeat_attempt_at = (
            time.time() - MIN_HEARTBEAT_INTERVAL_MS / 1000.0 - 1
        )
        assert manager._check_rate_limit() is True


# ---------------------------------------------------------------------------
# L7: Node ID legacy fallback
# ---------------------------------------------------------------------------


class TestLegacyNodeId:
    def test_migrate_evomap_prefix(self, manager: LifecycleManager) -> None:
        manager._state.node_id = "evomap-abc123"
        result = manager.resolve_legacy_node_id()
        assert result == "abc123"
        assert manager._state.original_node_id == "evomap-abc123"

    def test_migrate_node_prefix(self, manager: LifecycleManager) -> None:
        manager._state.node_id = "node-xyz789"
        result = manager.resolve_legacy_node_id()
        assert result == "xyz789"

    def test_no_migration_for_clean_id(self, manager: LifecycleManager) -> None:
        manager._state.node_id = "abc123def456"
        result = manager.resolve_legacy_node_id()
        assert result == "abc123def456"

    def test_none_id_returns_none(self, manager: LifecycleManager) -> None:
        manager._state.node_id = None
        assert manager.resolve_legacy_node_id() is None

    def test_effective_node_id_fallback(self, manager: LifecycleManager) -> None:
        manager._state.node_id = None
        manager._state.original_node_id = "evomap-old"
        assert manager.get_effective_node_id() == "evomap-old"


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


class TestStatePersistence:
    def test_save_and_load_secret_set_at(self) -> None:
        store = FakeStore()
        m1 = LifecycleManager(store=store)
        m1._state.secret_set_at = time.time()
        m1._save_state()
        # New manager from same store should load the value.
        m2 = LifecycleManager(store=store)
        assert m2._state.secret_set_at is not None

    def test_legacy_id_migration_on_load(self) -> None:
        store = FakeStore()
        store.set_state("node_id", "evomap-test123")
        m = LifecycleManager(store=store)
        # The _load_state should have migrated the prefix.
        assert m._state.node_id == "test123"
        assert m._state.original_node_id == "evomap-test123"


# ---------------------------------------------------------------------------
# Connection status
# ---------------------------------------------------------------------------


class TestConnectionStatus:
    def test_unregistered(self, manager: LifecycleManager) -> None:
        assert manager.connection_status == "unregistered"

    def test_connected_after_recent_heartbeat(self, manager: LifecycleManager) -> None:
        manager._state.node_id = "test"
        manager._state.last_heartbeat_at = int(time.time() * 1000)
        assert manager.connection_status == "connected"

    def test_idle_after_stale_heartbeat(self, manager: LifecycleManager) -> None:
        manager._state.node_id = "test"
        manager._state.last_heartbeat_at = 0  # very old
        assert manager.connection_status == "idle"
