"""Core Hub event delivery contracts (bridge + buffer + identity hooks)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Response

from evolver.proxy.event_delivery import (
    EventDeliveryManager,
    HubEventBridge,
    IdentityProvider,
    buffer_polled_hub_events,
    hub_open_event_stream,
    reset_hub_event_buffer,
    start_event_delivery,
    stop_event_delivery,
)
from evolver.proxy.mailbox.store import MailboxStore


@pytest.fixture
def store(tmp_path: Path) -> MailboxStore:
    return MailboxStore(tmp_path / "mailbox")


def test_bridge_accepts_hub_events_once_and_applies_trace_config(store: MailboxStore) -> None:
    handler_calls = {"n": 0}

    def on_inbound() -> None:
        handler_calls["n"] += 1

    bridge = HubEventBridge(store=store, on_inbound=on_inbound)
    stop_event_delivery()
    reset_hub_event_buffer()
    start_event_delivery(
        hub_url="",
        node_id="",
        enable_sse=False,
        on_events_accepted=bridge.accept_hub_events,
    )
    event = {
        "id": "evt_trace_stop",
        "type": "trace_collection_config",
        "payload": {"enabled": False},
    }
    try:
        assert len(buffer_polled_hub_events([event])) == 1
        assert store.get_state("trace_collection_enabled") == "false"
        msg = store.get_by_id(event["id"])
        assert msg is not None
        assert msg.status == "delivered"
        assert store.poll(type=event["type"]) == []
        assert handler_calls["n"] == 1

        assert len(buffer_polled_hub_events([event])) == 0
        assert handler_calls["n"] == 1
        assert bridge.accept_hub_events([event]) == 0
        assert handler_calls["n"] == 1
    finally:
        stop_event_delivery()
        bridge.stop()


@pytest.mark.asyncio
async def test_bridge_retries_failed_write_exactly_once(store: MailboxStore) -> None:
    bridge = HubEventBridge(store=store, retry_base_ms=20)
    original = store.write_inbound
    attempts = {"n": 0}

    def flaky_write(**kwargs: Any) -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise OSError("injected transient mailbox failure")
        return original(**kwargs)

    store.write_inbound = flaky_write  # type: ignore[method-assign]
    handler_calls = {"n": 0}
    bridge._on_inbound = lambda: handler_calls.__setitem__("n", handler_calls["n"] + 1)

    stop_event_delivery()
    reset_hub_event_buffer()
    start_event_delivery(
        hub_url="",
        enable_sse=False,
        on_events_accepted=bridge.accept_hub_events,
    )
    event = {
        "id": "evt_trace_retry",
        "type": "trace_collection_config",
        "payload": {"enabled": False},
    }
    try:
        assert len(buffer_polled_hub_events([event])) == 1
        assert store.get_by_id(event["id"]) is None
        assert bridge.pending_count == 1
        assert handler_calls["n"] == 0

        for _ in range(50):
            if store.get_by_id(event["id"]) is not None:
                break
            await asyncio.sleep(0.02)

        msg = store.get_by_id(event["id"])
        assert msg is not None and msg.status == "delivered"
        assert attempts["n"] == 2
        assert store.get_state("trace_collection_enabled") == "false"
        assert bridge.pending_count == 0
        assert handler_calls["n"] == 1

        assert len(buffer_polled_hub_events([event])) == 0
        await asyncio.sleep(0.05)
        assert attempts["n"] == 2
        assert handler_calls["n"] == 1
    finally:
        stop_event_delivery()
        bridge.stop()


@pytest.mark.asyncio
async def test_pending_retries_dedupe_and_stop_clears_timer(store: MailboxStore) -> None:
    bridge = HubEventBridge(store=store, retry_base_ms=25)
    attempts = {"n": 0}

    def always_fail(**_kwargs: Any) -> str:
        attempts["n"] += 1
        raise OSError("mailbox unavailable")

    store.write_inbound = always_fail  # type: ignore[method-assign]
    event = {"id": "evt_pending_shutdown", "type": "dm", "payload": {"content": "hello"}}

    assert bridge.accept_hub_events([event]) == 0
    assert bridge.accept_hub_events([event]) == 0
    assert attempts["n"] == 1
    assert bridge.pending_count == 1

    bridge.stop()
    assert bridge.pending_count == 0
    await asyncio.sleep(0.05)
    assert attempts["n"] == 1


@pytest.mark.asyncio
async def test_start_replaces_identity_subscription() -> None:
    unsub_a = {"n": 0}
    unsub_b = {"n": 0}
    provider_a = IdentityProvider(
        get_node_id=lambda: "node_aaaaaaaaaaaa",
        get_headers=lambda: {"Authorization": "Bearer " + "5" * 64},
        subscribe=lambda _cb: lambda: unsub_a.__setitem__("n", unsub_a["n"] + 1),
    )
    provider_b = IdentityProvider(
        get_node_id=lambda: "node_bbbbbbbbbbbb",
        get_headers=lambda: {"Authorization": "Bearer " + "6" * 64},
        subscribe=lambda _cb: lambda: unsub_b.__setitem__("n", unsub_b["n"] + 1),
    )
    mgr = EventDeliveryManager()
    try:
        mgr.start(hub_url="", identity_provider=provider_a, enable_sse=False)
        mgr.start(hub_url="", identity_provider=provider_b, enable_sse=False)
        assert unsub_a["n"] == 1
        mgr.stop()
        assert unsub_b["n"] == 1
    finally:
        mgr.stop()


@pytest.mark.asyncio
@respx.mock
async def test_hub_open_event_stream_uses_only_provided_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "6" * 64
    monkeypatch.setenv("A2A_NODE_SECRET", secret)
    route = respx.get("https://example.invalid/base/a2a/events/stream").mock(
        return_value=Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            content=b": connected\n\n",
        )
    )
    result = await hub_open_event_stream(
        hub_url="https://example.invalid/base",
        node_id="issue600-node",
        duration_ms=12345,
        headers={
            "Authorization": f"Bearer {secret}",
            "X-EvoMap-Node-Secret-Version": "8",
        },
    )
    assert result["ok"] is True
    assert route.called
    req = route.calls.last.request
    assert "node_id=issue600-node" in str(req.url)
    assert "duration_ms=12345" in str(req.url)
    assert req.headers.get("Authorization") == f"Bearer {secret}"
    assert req.headers.get("X-EvoMap-Node-Secret-Version") == "8"
    # Must not inject host cookie-style credentials.
    assert "Cookie" not in req.headers
    close = result.get("close")
    if callable(close):
        close()


def test_healthy_sse_state_suppresses_poll_flag() -> None:
    """Unit contract: healthy SSE flips selfDrivingPollEnabled off."""
    mgr = EventDeliveryManager()
    mgr._state.running = True
    mgr._state.sse_healthy = True
    mgr._state.self_driving_poll_enabled = False
    internals = mgr.get_internals()
    assert internals["sseHealthy"] is True
    assert internals["selfDrivingPollEnabled"] is False


def test_recover_after_wake_reenables_poll() -> None:
    mgr = EventDeliveryManager()
    mgr._state.running = True
    mgr._state.sse_healthy = True
    mgr._state.self_driving_poll_enabled = False
    mgr.recover_after_wake()
    internals = mgr.get_internals()
    assert internals["sseHealthy"] is False
    assert internals["selfDrivingPollEnabled"] is True
