"""Tests for evolver.webui.client.sse."""

from __future__ import annotations

from evolver.webui.client.sse import (
    API_LOGS_PATH,
    EVENTS_STREAM_PATH,
    render_sse_client_js,
)


class TestSseClientModule:
    def test_default_paths(self) -> None:
        assert EVENTS_STREAM_PATH == "/events/stream"
        assert API_LOGS_PATH == "/api/logs"

    def test_render_sse_client_js_injects_paths(self) -> None:
        js = render_sse_client_js(
            stream_path="/custom/stream",
            logs_path="/custom/logs",
        )
        assert "/custom/stream" in js
        assert "/custom/logs" in js
        assert "EventSource" in js
        assert "SSE.connect" in js
        assert "SSE.onConnect" in js

    def test_render_sse_client_js_default_placeholders_replaced(self) -> None:
        js = render_sse_client_js()
        assert "__EVENT_STREAM_PATH__" not in js
        assert EVENTS_STREAM_PATH in js
