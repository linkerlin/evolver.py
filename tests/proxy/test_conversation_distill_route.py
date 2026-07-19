"""Sprint 15.4 — POST /conversation/distill route E2E (proxyServer contract)."""

# ruff: noqa: E501

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from evolver.proxy.server.routes import router

VALID_CONVERSATION = {
    "summary": ("Reusable Evolver distill endpoint compatibility workflow for MCP plugin bridges."),
    "assistant_summary": (
        "Added a Proxy conversation distillation bridge so Codex, Claude Code, Cursor, "
        "WorkBuddy, and Antigravity plugins can publish Genes and Capsules without hitting a 404."
    ),
    "strategy": [
        "Verify each plugin bridge calls the same Proxy route before changing repository code.",
        "Keep the Proxy route on the current signed asset publish path instead of the old mailbox submit path.",
        "Add focused tests for draft distillation, publish forwarding, and low quality skipped inputs.",
    ],
    "artifacts": [
        "src/proxy/server/routes.js",
        "src/gep/conversationDistiller.js",
    ],
    "validation": ["node --test test/proxyServer.test.js"],
    "signals": ["distill_endpoint", "proxy_compatibility", "test_verified"],
}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evomap"))
    monkeypatch.delenv("EVOMAP_PROXY_TOKEN", raising=False)
    monkeypatch.delenv("A2A_HUB_URL", raising=False)
    app = FastAPI()
    app.include_router(router, prefix="/v1/a2a")
    return TestClient(app)


def test_distill_draft_when_publish_and_persist_disabled(client: TestClient) -> None:
    res = client.post(
        "/v1/a2a/conversation/distill",
        json={**VALID_CONVERSATION, "persist": False, "publish": False},
        headers={"Authorization": "Bearer " + "a" * 64},
    )
    # Open mode when no token configured, or 401 if token required — set open mode
    if res.status_code == 401:
        # Authorize open: empty candidates → authorize_bearer True
        pass
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["status"] == "draft"
    assert body["published"] is False
    assert body["publish_result"] is None
    assert body["gene"]["type"] == "Gene"
    assert body["capsule"]["type"] == "Capsule"
    assert body["capsule"]["blast_radius"] == {"files": 1, "lines": 1}
    assert isinstance(body["capsule"]["content"], str)
    assert isinstance(body["capsule"]["diff"], str)
    assert isinstance(body["capsule"]["reused_asset_id"], str)
    assert isinstance(body["capsule"]["env_fingerprint"], dict)


def test_publishes_gene_and_capsule(client: TestClient) -> None:
    res = client.post(
        "/v1/a2a/conversation/distill",
        json={**VALID_CONVERSATION, "persist": False},
        headers={"Authorization": "Bearer " + "a" * 64},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["published"] is True
    assert body["publish_result"]["published"] == 2
    assert body["publish_result"]["total"] == 2


def test_skips_low_signal(client: TestClient) -> None:
    res = client.post(
        "/v1/a2a/conversation/distill",
        json={"summary": "too short", "publish": False},
        headers={"Authorization": "Bearer " + "a" * 64},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["status"] == "skipped"
