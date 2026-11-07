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
    record_outcome,
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

    def test_floor_caps_wait_after_many_reprobes(self) -> None:
        """Round-65 doctrine: the halving converges to a 1h floor — after
        many failed re-probes (naive halving < 1h) the wait must not go
        below it: probe frequency converges instead of approaching zero."""
        import time as _time

        # 30 re-probes → naive halving would be 24h/31 (~0.77h), BELOW the
        # 1h floor — the floor must bind at exactly 1h.
        state = load_state()
        state["consecutive_404"] = HUB_404_STICKY_THRESHOLD
        state["reprobe_count"] = 30
        state["last_probe_ts"] = _time.time() - 1800  # 0.5h ago < floor
        save_state(state)
        assert endpoint_sticky() is True, "floor keeps the wait at 1h minimum"

        # 1.5h later (> floor): sticky must EXPIRE — probes happen at
        # least hourly no matter how many failures accumulate.
        state["last_probe_ts"] = _time.time() - 5400
        save_state(state)
        assert endpoint_sticky() is False, "floor caps the wait at 1h"


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


class TestRecordOutcome:
    """Round-120: the sticky counter has ONE write path fed by every Hub
    consumer — until now only the pipeline hub phase wrote it, so sparse
    host-driven ticks (days apart) never converged and post_cycle's pickup
    burned the dead endpoint every cycle in between."""

    _404 = "Client error '404 Not Found' for url 'https://hub/v1/a2a/tasks'"

    def test_404_observations_converge_within_one_cycle(self) -> None:
        record_outcome(ok=False, error_text=self._404)
        state = load_state()
        assert state["consecutive_404"] == 1
        assert endpoint_sticky() is False
        # fetch_tasks + pick_one in the SAME cycle: threshold crossed
        # without waiting for three real ticks.
        record_outcome(ok=False, error_text=self._404)
        record_outcome(ok=False, error_text=self._404)
        assert load_state()["consecutive_404"] == HUB_404_STICKY_THRESHOLD
        assert endpoint_sticky() is True

    def test_threshold_crossing_starts_reprobe_halving(self) -> None:
        for _ in range(HUB_404_STICKY_THRESHOLD):
            record_outcome(ok=False, error_text=self._404)
        assert load_state()["reprobe_count"] == 1, "round-65 halving starts at the crossing"
        # A further 404 below threshold... cannot happen once sticky, but the
        # reprobe note must not double-fire per observation beyond crossing.
        record_outcome(ok=False, error_text=self._404)
        assert load_state()["reprobe_count"] == 2, "each sticky-window 404 is a failed re-probe"

    def test_success_resets(self) -> None:
        for _ in range(HUB_404_STICKY_THRESHOLD):
            record_outcome(ok=False, error_text=self._404)
        record_outcome(ok=True)
        state = load_state()
        assert state["consecutive_404"] == 0
        assert state["reprobe_count"] == 0
        assert endpoint_sticky() is False

    def test_non_404_failure_resets(self) -> None:
        for _ in range(HUB_404_STICKY_THRESHOLD):
            record_outcome(ok=False, error_text=self._404)
        record_outcome(ok=False, error_text="DNS lookup failed")
        assert load_state()["consecutive_404"] == 0, (
            "a different failure class says nothing about the endpoint's existence"
        )

    async def test_hub_client_404_feeds_shared_counter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The round-46 gap, pinned: hub_client used to only READ the sticky
        state — its own 404s never counted."""
        import httpx

        from evolver.atp import hub_client

        state = load_state()
        state["consecutive_404"] = HUB_404_STICKY_THRESHOLD - 1
        state["last_probe_ts"] = time.time()
        save_state(state)

        class _FakeResp:
            def raise_for_status(self) -> None:
                raise httpx.HTTPStatusError(
                    "Client error '404 Not Found'",
                    request=httpx.Request("GET", "https://hub/v1/a2a/atp/tasks"),
                    response=httpx.Response(404),
                )

            def json(self) -> dict[str, object]:
                return {}

        class _FakeClient:
            def __init__(self, *a: object, **kw: object) -> None:
                pass

            async def __aenter__(self) -> _FakeClient:
                return self

            async def __aexit__(self, *a: object) -> None:
                pass

            async def get(self, *a: object, **kw: object) -> _FakeResp:
                return _FakeResp()

        monkeypatch.setattr(hub_client.httpx, "AsyncClient", _FakeClient)
        result = await hub_client.list_my_tasks()
        assert result["ok"] is False
        assert result["status"] == 404
        assert load_state()["consecutive_404"] == HUB_404_STICKY_THRESHOLD
        assert endpoint_sticky() is True, "one pickup 404 closes the convergence gap"

    async def test_hub_client_success_resets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from evolver.atp import hub_client

        # Threshold-1: below the sticky gate so the HTTP path actually runs.
        for _ in range(HUB_404_STICKY_THRESHOLD - 1):
            record_outcome(ok=False, error_text=self._404)

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
                return _FakeResp()

        monkeypatch.setattr(hub_client.httpx, "AsyncClient", _FakeClient)
        result = await hub_client.list_my_tasks()
        assert result["ok"] is True
        state = load_state()
        assert state["consecutive_404"] == 0
        assert endpoint_sticky() is False
