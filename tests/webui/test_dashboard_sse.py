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

    def test_includes_pipeline_insights(self) -> None:
        html = render_dashboard()
        assert 'id="insights-diagnosis"' in html
        assert 'id="insights-hub"' in html
        assert 'id="insights-autopoiesis"' in html
        assert 'id="insights-memory-sync"' in html
        assert "/api/insights" in html

    def test_sse_refreshes_insights_on_event(self) -> None:
        html = render_dashboard()
        assert "scheduleInsightsRefresh" in html
        assert "insights-memory-sync" in html
