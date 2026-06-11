"""Tests for evolver.proxy.server.routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from evolver.proxy.mailbox.store import MailboxStore
from evolver.proxy.server.routes import router


def _make_client(store: MailboxStore) -> TestClient:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router, prefix="/v1/a2a")
    app.state.mailbox_store = store
    return TestClient(app)


@pytest.fixture
def client(temp_workspace: Path) -> TestClient:
    store = MailboxStore(temp_workspace / "mailbox")
    return _make_client(store)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_proxy_status_no_auth(client: TestClient) -> None:
    resp = client.get("/v1/a2a/proxy/status")
    assert resp.status_code == 200


def test_mailbox_send_requires_auth(client: TestClient) -> None:
    resp = client.post("/v1/a2a/mailbox/send", json={"type": "test", "payload": {}})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Mailbox
# ---------------------------------------------------------------------------


def test_mailbox_send_and_poll(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.post(
        "/v1/a2a/mailbox/send",
        json={"type": "test", "payload": {"x": 1}},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"

    resp = client.post(
        "/v1/a2a/mailbox/poll",
        json={},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200


def test_mailbox_ack(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    # write inbound
    store = client.app.state.mailbox_store
    store.write_inbound(id="m1", type="t", payload={})
    resp = client.post(
        "/v1/a2a/mailbox/ack",
        json={"message_ids": ["m1"]},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200
    assert resp.json()["acked"] == 1


def test_mailbox_list(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.get("/v1/a2a/mailbox/list", headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 200
    assert "messages" in resp.json()


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


def test_asset_validate(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.post(
        "/v1/a2a/asset/validate",
        json={"payload": {}},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


def test_asset_submissions(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.get("/v1/a2a/asset/submissions", headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 200
    assert "submissions" in resp.json()


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def test_task_list(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.get("/v1/a2a/task/list", headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 200
    assert "tasks" in resp.json()


# ---------------------------------------------------------------------------
# DM
# ---------------------------------------------------------------------------


def test_dm_send(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.post(
        "/v1/a2a/dm/send",
        json={"to": "user1", "payload": {"msg": "hi"}},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200
    assert "message_id" in resp.json()


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


def test_session_create(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.post(
        "/v1/a2a/session/create",
        json={},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200
    assert "session_id" in resp.json()


# ---------------------------------------------------------------------------
# ATP
# ---------------------------------------------------------------------------


def test_atp_order(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.post(
        "/v1/a2a/atp/order",
        json={"service_id": "svc1"},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200
    assert "order_id" in resp.json()


def test_atp_policy(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.get("/v1/a2a/atp/policy", headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 200
    assert "policy" in resp.json()


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


def test_llm_messages_no_handler(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.post(
        "/v1/a2a/v1/messages",
        json={"model": "claude", "messages": []},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 503
