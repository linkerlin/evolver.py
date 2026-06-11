"""Tests for evolver.proxy.server.routes."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from evolver.proxy.extensions.dm_handler import create_dm_handler
from evolver.proxy.extensions.session_handler import SessionHandler
from evolver.proxy.extensions.skill_updater import create_skill_updater
from evolver.proxy.mailbox.store import MailboxStore
from evolver.proxy.server.routes import router
from evolver.proxy.task.monitor import TaskMonitor


def _make_client(store: MailboxStore) -> TestClient:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router, prefix="/v1/a2a")
    app.state.mailbox_store = store
    app.state.session_handler = SessionHandler()
    app.state.task_monitor = TaskMonitor()
    app.state.dm_handler = create_dm_handler()
    app.state.skill_updater = create_skill_updater(mailbox_store=store)
    app.state.atp_orders = {}
    app.state.atp_proofs = []
    app.state.claimed_tasks = {}
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


def test_asset_validate_rejects_empty(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.post(
        "/v1/a2a/asset/validate",
        json={"payload": {}},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 400
    assert resp.json()["valid"] is False


def test_asset_validate_accepts_gene(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.post(
        "/v1/a2a/asset/validate",
        json={
            "payload": {
                "type": "Gene",
                "id": "gene-test-1",
                "category": "repair",
                "summary": "test gene",
            }
        },
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


def test_asset_submissions(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.get("/v1/a2a/asset/submissions", headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 200
    assert "submissions" in resp.json()


def test_asset_fetch_requires_id_or_url(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.post(
        "/v1/a2a/asset/fetch",
        json={},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "missing_asset_id_or_url"


def test_asset_fetch_hub_asset_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    mock_download = AsyncMock(
        return_value={"ok": True, "asset": {"id": "g1", "type": "Gene", "category": "repair"}}
    )
    monkeypatch.setattr("evolver.gep.fetch.download_asset", mock_download)
    resp = client.post(
        "/v1/a2a/asset/fetch",
        json={"asset_id": "raw:g1"},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["source"] == "hub"
    assert data["asset"]["id"] == "g1"


def test_asset_search_local_fallback(
    client: TestClient, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evolver.gep import fetch as gep_fetch

    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    monkeypatch.setattr(gep_fetch, "get_hub_url", lambda: None)
    monkeypatch.setattr("evolver.gep.paths.get_repo_root", lambda: temp_workspace)
    (temp_workspace / "docs").mkdir()
    (temp_workspace / "docs" / "repair-guide.md").write_text("x", encoding="utf-8")

    resp = client.post(
        "/v1/a2a/asset/search",
        json={"keyword": "repair", "local": True},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["source"] == "local"
    assert any("repair" in r["name"] for r in data["results"])


def test_asset_search_hub(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    mock_search = AsyncMock(
        return_value={"ok": True, "assets": [{"id": "g1", "type": "Gene"}]}
    )
    monkeypatch.setattr("evolver.gep.fetch.search_assets", mock_search)
    resp = client.post(
        "/v1/a2a/asset/search",
        json={"query": "repair"},
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["source"] == "hub"
    assert data["total"] == 1


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def test_task_list(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.get("/v1/a2a/task/list", headers={"Authorization": "Bearer secret"})
    assert resp.status_code == 200
    assert "tasks" in resp.json()


def test_task_claim_and_metrics(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    headers = {"Authorization": "Bearer secret"}
    resp = client.post(
        "/v1/a2a/task/subscribe",
        json={"types": ["repair"]},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["subscribed"] is True

    resp = client.post(
        "/v1/a2a/task/claim",
        json={"task_id": "task-42"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["task_id"] == "task-42"

    resp = client.post(
        "/v1/a2a/task/complete",
        json={"task_id": "task-42"},
        headers=headers,
    )
    assert resp.status_code == 200

    resp = client.get("/v1/a2a/task/metrics", headers=headers)
    metrics = resp.json()
    assert metrics["tasks_claimed"] == 1
    assert metrics["tasks_completed"] == 1


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
    data = resp.json()
    assert "policy" in data
    assert "balance" in data


def test_atp_order_lifecycle(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    headers = {"Authorization": "Bearer secret"}
    resp = client.post("/v1/a2a/atp/order", json={"service_id": "svc1"}, headers=headers)
    assert resp.status_code == 200
    order_id = resp.json()["order_id"]

    resp = client.get(f"/v1/a2a/atp/order/{order_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"

    resp = client.post(
        "/v1/a2a/atp/deliver",
        json={"order_id": order_id, "proof": {"ok": True}},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "delivered"


# ---------------------------------------------------------------------------
# Skill extensions
# ---------------------------------------------------------------------------


def test_extensions_skills_updates(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.get(
        "/v1/a2a/extensions/skills/updates",
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "updates" in data


def test_extensions_skills_process(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.post(
        "/v1/a2a/extensions/skills/process",
        headers={"Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "applied" in data


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


def test_llm_messages_routes_to_upstream(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/v1/messages routes to handle_messages; expect upstream error without API key."""
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", "secret")
    resp = client.post(
        "/v1/a2a/v1/messages",
        json={"model": "claude", "messages": []},
        headers={"Authorization": "Bearer secret"},
    )
    # No API key: upstream 401 from Anthropic or proxy 502/504
    assert resp.status_code in (401, 402, 403, 502, 504)
