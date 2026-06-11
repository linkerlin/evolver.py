"""Tests that the main dashboard HTML wires SSE live updates."""

from __future__ import annotations

from evolver.webui.dashboard import render_dashboard


class TestDashboardSse:
    def test_includes_sse_client_and_stream_path(self) -> None:
        html = render_dashboard()
        assert "EvolverSSE" in html
        assert "/events/stream" in html
        assert 'id="events-tbody"' in html

    def test_no_meta_refresh(self) -> None:
        html = render_dashboard()
        assert "http-equiv" not in html
