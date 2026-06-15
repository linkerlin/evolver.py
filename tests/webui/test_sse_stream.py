"""SSE streaming tests for WebUI ``/events/stream`` and ``/api/logs``."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from evolver.webui.app import app as main_app


@pytest.fixture
def webui_client() -> TestClient:
    return TestClient(main_app)


def _parse_sse_data(body: str) -> list[dict]:
    events: list[dict] = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


class TestEventsStream:
    def test_stream_content_type(self, webui_client: TestClient) -> None:
        resp = webui_client.get("/events/stream", headers={"x-test-mode": "1"})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"

    def test_stream_delivers_new_event(
        self, webui_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}

        def _read_events() -> list[dict]:
            calls["n"] += 1
            if calls["n"] <= 1:
                return []
            return [{"id": "evt-1", "type": "cycle_end"}]

        monkeypatch.setattr("evolver.webui.server.legacy_routes.read_all_events", _read_events)
        body = webui_client.get("/events/stream", headers={"x-test-mode": "1"}).text
        parsed = _parse_sse_data(body)
        assert any(evt.get("id") == "evt-1" for evt in parsed)

    def test_stream_sends_keepalive_ping(
        self, webui_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("evolver.webui.server.legacy_routes.read_all_events", lambda: [])
        body = webui_client.get("/events/stream", headers={"x-test-mode": "1"}).text
        assert ":ping" in body


class TestApiLogsStream:
    def test_logs_stream_delivers_event(
        self, webui_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}

        def _read_events() -> list[dict]:
            calls["n"] += 1
            if calls["n"] <= 1:
                return []
            return [{"id": "log-1", "type": "invoke"}]

        monkeypatch.setattr("evolver.webui.server.routes.read_all_events", _read_events)
        body = webui_client.get("/api/logs", headers={"x-test-mode": "1"}).text
        parsed = _parse_sse_data(body)
        assert any(evt.get("id") == "log-1" for evt in parsed)
