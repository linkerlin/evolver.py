"""Tests for evolver.webui.app."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from evolver.webui.app import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def isolated_evolver_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("EVOLVER_USER_LOCK", str(tmp_path / "user.lock"))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evolver"))
    yield tmp_path


def test_root_html(client: TestClient, isolated_evolver_env: Path) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Evolver Dashboard" in response.text
    assert "Genes" in response.text
    assert "Capsules" in response.text
    assert "Recent Events" in response.text


def test_status_empty(client: TestClient, isolated_evolver_env: Path) -> None:
    response = client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert data["solidify_pending"] is False
    assert data["total_events"] == 0


def test_genes_endpoint(client: TestClient, isolated_evolver_env: Path) -> None:
    response = client.get("/genes")
    assert response.status_code == 200
    data = response.json()
    assert "genes" in data
    assert len(data["genes"]) >= 3  # seed genes


def test_capsules_endpoint(client: TestClient, isolated_evolver_env: Path) -> None:
    response = client.get("/capsules")
    assert response.status_code == 200
    data = response.json()
    assert "capsules" in data


def test_peers_endpoint(client: TestClient, isolated_evolver_env: Path) -> None:
    response = client.get("/api/peers")
    assert response.status_code == 200
    data = response.json()
    assert "peers" in data


def test_events_endpoint(client: TestClient, isolated_evolver_env: Path) -> None:
    response = client.get("/events")
    assert response.status_code == 200
    data = response.json()
    assert "events" in data


def test_events_stream(client: TestClient, isolated_evolver_env: Path) -> None:
    response = client.get("/events/stream", headers={"X-Test-Mode": "1"})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    body = response.text
    assert ":ping" in body


def test_websocket_ping(client: TestClient, isolated_evolver_env: Path) -> None:
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()
        assert data["type"] == "connected"
        ws.send_json({"action": "ping"})
        data = ws.receive_json()
        assert data["type"] == "pong"


def test_websocket_status(client: TestClient, isolated_evolver_env: Path) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # connected
        ws.send_json({"action": "status"})
        data = ws.receive_json()
        assert data["type"] == "status"
        assert "solidify_pending" in data


def test_websocket_run(client: TestClient, isolated_evolver_env: Path) -> None:
    from evolver.ops.auth_middleware import create_token

    token = create_token(role="admin")
    with client.websocket_connect("/ws", headers={"Authorization": f"Bearer {token}"}) as ws:
        ws.receive_json()  # connected
        ws.send_json({"action": "run"})
        data = ws.receive_json()
        assert data["type"] == "status"


def test_websocket_run_unauthorized(client: TestClient, isolated_evolver_env: Path) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()  # connected
        ws.send_json({"action": "run"})
        with pytest.raises(Exception):
            ws.receive_json()


def test_websocket_run_with_query_token(client: TestClient, isolated_evolver_env: Path) -> None:
    from evolver.ops.auth_middleware import create_token

    token = create_token(role="admin")
    with client.websocket_connect(f"/ws?token={token}") as ws:
        ws.receive_json()  # connected
        ws.send_json({"action": "run"})
        data = ws.receive_json()
        assert data["type"] == "status"
