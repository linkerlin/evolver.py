"""Tests for unified WebUI ``create_app`` / ``WebUiServer``."""

from __future__ import annotations

from fastapi.testclient import TestClient

from evolver.webui.app import app as app_entry
from evolver.webui.server.http import WebUiServer, create_app


def test_app_entry_matches_create_app() -> None:
    assert app_entry.title == create_app().title
    assert sorted(route.path for route in app_entry.routes) == sorted(
        route.path for route in create_app().routes
    )


def test_create_app_serves_dashboard_and_modular_client() -> None:
    client = TestClient(create_app())
    root = client.get("/")
    assert root.status_code == 200
    assert "Evolver Dashboard" in root.text

    classic = client.get("/classic")
    assert classic.status_code == 200
    assert "/app.js" in classic.text

    js = client.get("/app.js")
    assert js.status_code == 200
    assert "scheduleInsightsRefresh" in js.text or "bootstrap" in js.text.lower()

    css = client.get("/app.css")
    assert css.status_code == 200
    assert "background" in css.text


def test_webui_server_uses_same_app_factory() -> None:
    server = WebUiServer(port=18080)
    assert server.app.title == create_app().title
