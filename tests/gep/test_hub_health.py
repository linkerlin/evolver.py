"""Tests for evolver.gep.hub_health + hub_client sticky preflight (round-46).

Round-48: state seeding/inspection goes through the hub_health API — the
conftest autouse fixture redirects state_path per-test, so raw-file paths
under EVOLUTION_DIR would silently miss.
"""

from __future__ import annotations

import time

import pytest

from evolver.gep.hub_health import (
    HUB_404_STICKY_THRESHOLD,
    endpoint_sticky,
    load_state,
    note_404,
    reset_404,
    save_state,
)


class TestHubHealth:
    def test_endpoint_sticky_after_threshold(self) -> None:
        state = load_state()
        for _ in range(HUB_404_STICKY_THRESHOLD):
            state = note_404(state)
        save_state(state)

        # last_probe_ts is now — sticky must hold.
        assert endpoint_sticky() is True
        # TTL-expired probe window fails the sticky check (ancient ts).
        state["last_probe_ts"] = time.time() - 10**9
        save_state(state)
        assert endpoint_sticky() is False

    def test_below_threshold_not_sticky(self) -> None:
        save_state(
            {
                "consecutive_404": HUB_404_STICKY_THRESHOLD - 1,
                "last_probe_ts": 1e12,
            }
        )
        assert endpoint_sticky() is False

    def test_reset_clears_counter(self) -> None:
        state = reset_404({"consecutive_404": 3, "last_probe_ts": 1e12})
        assert state["consecutive_404"] == 0
        assert endpoint_sticky() is False


class TestHubClientPreflight:
    async def test_sticky_skips_http_entirely(self, monkeypatch: pytest.MonkeyPatch) -> None:
        save_state(
            {
                "consecutive_404": HUB_404_STICKY_THRESHOLD,
                "last_probe_ts": time.time(),
            }
        )
        from evolver.atp import hub_client

        def _no_client(*args: object, **kwargs: object) -> None:
            raise AssertionError("sticky preflight must not construct an HTTP client")

        monkeypatch.setattr(hub_client.httpx, "AsyncClient", _no_client)
        result = await hub_client.list_my_tasks()
        assert result["ok"] is False
        assert result["error"] == "hub_endpoint_missing"

    async def test_not_sticky_proceeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # No state seeded → not sticky.
        from evolver.atp import hub_client

        calls = {"n": 0}

        class _FakeResp:
            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, object]:
                return {"tasks": []}

        class _FakeClient:
            def __init__(self, *a: object, **kw: object) -> None:
                pass

            async def __aenter__(self) -> _FakeClient:
                return self

            async def __aexit__(self, *a: object) -> None:
                pass

            async def get(self, *a: object, **kw: object) -> _FakeResp:
                calls["n"] += 1
                return _FakeResp()

        monkeypatch.setattr(hub_client.httpx, "AsyncClient", _FakeClient)
        result = await hub_client.list_my_tasks()
        assert calls["n"] == 1, "non-sticky must hit HTTP as before"
        assert result["ok"] is True
