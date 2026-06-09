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


def test_events_endpoint(client: TestClient, isolated_evolver_env: Path) -> None:
    response = client.get("/events")
    assert response.status_code == 200
    data = response.json()
    assert "events" in data
