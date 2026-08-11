"""SSE planned close semantics (v1.94.0 parity, issues #606/#594).

Behavioral port of Node ``test/ssePlannedClose.test.js``: the Hub clamps
``duration_ms`` to 300s and ends the stream deliberately with an
``event: close`` frame; a planned close must reconnect at the base interval
instead of being charged to the failure backoff.
"""

from __future__ import annotations

import json

import pytest

from evolver.proxy.event_delivery import (
    SSE_RECONNECT_BASE_MS,
    SSE_RECONNECT_MAX_MS,
    SSE_STREAM_DURATION_MS,
    EventDeliveryManager,
)


@pytest.fixture
def mgr() -> EventDeliveryManager:
    return EventDeliveryManager()


class TestSsePlannedClose:
    def test_requests_duration_within_hub_ceiling(self) -> None:
        assert 0 < SSE_STREAM_DURATION_MS <= 300_000

    def test_latches_planned_close_and_reports_it_exactly_once(self, mgr: EventDeliveryManager) -> None:
        mgr.handle_hub_event_stream_close(json.dumps({"reason": "max_duration"}))
        assert mgr.take_sse_planned_close() is True, "first read must see the planned close"
        assert mgr.take_sse_planned_close() is False, "flag must be consumed, not sticky"

    def test_non_json_close_frame_is_planned_too(self, mgr: EventDeliveryManager) -> None:
        mgr.handle_hub_event_stream_close("bye")
        assert mgr.take_sse_planned_close() is True

    def test_close_frame_with_no_data_is_planned(self, mgr: EventDeliveryManager) -> None:
        mgr.handle_hub_event_stream_close()
        assert mgr.take_sse_planned_close() is True

    def test_no_planned_close_when_hub_never_sent_one(self, mgr: EventDeliveryManager) -> None:
        assert mgr.take_sse_planned_close() is False

    def test_fetch_fallback_dispatches_named_close_frames(self, mgr: EventDeliveryManager) -> None:
        seen: list[dict] = []

        class FakeEventSource:
            def __init__(self) -> None:
                self.listeners: dict[str, list] = {}

            def onmessage(self, ev: dict) -> None:
                raise AssertionError("named close must not be delivered through onmessage")

            def addEventListener(self, event_type: str, fn) -> None:  # type: ignore[no-untyped-def]
                self.listeners.setdefault(event_type, []).append(fn)

            def _dispatch_event(self, event_type: str, ev: dict) -> None:
                for fn in self.listeners.get(event_type, []):
                    fn(ev)

        es = FakeEventSource()
        es.addEventListener("close", lambda ev: seen.append(ev))

        EventDeliveryManager.emit_fetch_sse_frame_for_testing(
            es, 'event: close\ndata: {"reason":"max_duration"}\n\n'
        )

        assert seen, "fetch fallback must dispatch named close events"
        assert seen[0]["type"] == "close"
        assert seen[0]["data"] == '{"reason":"max_duration"}'

    def test_fetch_fallback_dispatches_ordinary_messages(self, mgr: EventDeliveryManager) -> None:
        seen: list[dict] = []

        class FakeEventSource:
            def onmessage(self, ev: dict) -> None:
                seen.append(ev)

            def _dispatch_event(self, event_type: str, ev: dict) -> None:  # type: ignore[no-untyped-def]
                raise AssertionError("message frames must go through onmessage")

        EventDeliveryManager.emit_fetch_sse_frame_for_testing(
            FakeEventSource(), "data: hello\n\n"
        )
        assert len(seen) == 1
        assert seen[0]["type"] == "message"
        assert seen[0]["data"] == "hello"

    def test_planned_close_resets_saturated_backoff_to_base(self, mgr: EventDeliveryManager) -> None:
        for _ in range(6):
            mgr._grow_sse_reconnect_backoff()
        assert mgr.get_sse_internals_for_testing()["sseReconnectMs"] == SSE_RECONNECT_MAX_MS

        # This is what the reconnect path does on a planned close.
        mgr.handle_hub_event_stream_close(json.dumps({"reason": "max_duration"}))
        if mgr.take_sse_planned_close():
            mgr.reset_sse_reconnect_backoff()

        assert mgr.get_sse_internals_for_testing()["sseReconnectMs"] == SSE_RECONNECT_BASE_MS

    def test_unplanned_end_grows_backoff(self, mgr: EventDeliveryManager) -> None:
        mgr._grow_sse_reconnect_backoff()
        assert mgr.get_sse_internals_for_testing()["sseReconnectMs"] == SSE_RECONNECT_BASE_MS * 2

    def test_close_frame_during_stream_latches(self, mgr: EventDeliveryManager) -> None:
        mgr._dispatch_sse_frame("close", '{"reason":"max_duration"}')
        assert mgr.get_sse_internals_for_testing()["ssePlannedClose"] is True

    def test_message_frame_without_id_gets_synthesized_id(self, mgr: EventDeliveryManager) -> None:
        mgr._dispatch_sse_frame("message", json.dumps({"type": "task_assigned", "payload": {"x": 1}}))
        internals = mgr.get_sse_internals_for_testing()
        assert internals["ssePlannedClose"] is False
