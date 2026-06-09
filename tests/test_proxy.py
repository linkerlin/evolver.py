"""Tests for evolver.proxy.server."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from evolver.proxy.server import app, _trace


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_trace() -> None:
    _trace.clear()


class TestHealth:
    def test_health_ok(self, client: TestClient) -> None:
        response = client.get("/v1/a2a/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestProxyForward:
    def test_invalid_json(self, client: TestClient) -> None:
        response = client.post("/v1/a2a/proxy/hello", data="not-json")
        assert response.status_code == 400
        assert response.json()["error"] == "invalid_json"

    def test_trace_empty(self, client: TestClient) -> None:
        response = client.get("/v1/a2a/trace")
        assert response.status_code == 200
        assert response.json()["trace"] == []

    def test_trace_limit(self, client: TestClient) -> None:
        for i in range(5):
            _trace.append({"ts": i})
        response = client.get("/v1/a2a/trace?limit=3")
        assert response.status_code == 200
        assert len(response.json()["trace"]) == 3
