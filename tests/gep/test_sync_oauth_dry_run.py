"""Ports Node ``syncOAuthDryRun.test.js`` — OAuth-only published dry-run auth."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import respx
from httpx import Response

from evolver.gep import node_identity as ni
from evolver.gep import sync
from evolver.gep.oauth_login import load_valid_oauth_access_token

NODE_ID = "node_a0b1c2d3e4f5"
OAUTH_TOKEN = "oauth-access-token"


@pytest.fixture
def oauth_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    (home / "node_id").write_text(NODE_ID, encoding="utf-8")
    monkeypatch.setenv("EVOLVER_HOME", str(home))
    monkeypatch.setenv("A2A_HUB_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EVOMAP_HUB_ALLOW_INSECURE", "1")
    for key in (
        "A2A_NODE_ID",
        "A2A_NODE_SECRET",
        "A2A_NODE_SECRET_VERSION",
        "EVOMAP_NODE_SECRET",
        "A2A_HUB_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(ni, "project_local_node_id_path", lambda: None)
    ni.reset_cached_node_id()
    yield home
    ni.reset_cached_node_id()


def _snapshot(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in root.rglob("*"):
        if path.is_file():
            out[str(path.relative_to(root))] = path.read_bytes().hex()
    return out


def test_load_valid_oauth_token_accepts_future_expiry(oauth_home: Path) -> None:
    (oauth_home / "oauth_token.json").write_text(
        json.dumps(
            {
                "access_token": OAUTH_TOKEN,
                "expires_at": int(time.time() * 1000) + 3_600_000,
                "scope": "intentionally-not-trusted-by-cli",
            }
        ),
        encoding="utf-8",
    )
    assert load_valid_oauth_access_token() == OAUTH_TOKEN


def test_load_valid_oauth_token_rejects_expired(oauth_home: Path) -> None:
    (oauth_home / "oauth_token.json").write_text(
        json.dumps(
            {
                "access_token": OAUTH_TOKEN,
                "expires_at": int(time.time() * 1000) - 60_000,
            }
        ),
        encoding="utf-8",
    )
    assert load_valid_oauth_access_token() is None


@respx.mock
async def test_sync_dry_run_oauth_only_reaches_hub_without_writes(
    oauth_home: Path,
) -> None:
    (oauth_home / "oauth_token.json").write_text(
        json.dumps(
            {
                "access_token": OAUTH_TOKEN,
                "expires_at": int(time.time() * 1000) + 3_600_000,
            }
        ),
        encoding="utf-8",
    )
    before = _snapshot(oauth_home)
    route = respx.get("http://127.0.0.1:9/a2a/assets/published-by-me").mock(
        return_value=Response(200, json={"assets": [], "count": 0})
    )
    result = await sync.sync_all(dry_run=True, scope="published")
    assert result["ok"] is True
    assert route.called
    req = route.calls.last.request
    assert req.headers.get("Authorization") == f"Bearer {OAUTH_TOKEN}"
    assert req.url.params.get("node_id") == NODE_ID
    assert _snapshot(oauth_home) == before


@respx.mock
async def test_sync_dry_run_rejects_expired_oauth_before_request(
    oauth_home: Path,
) -> None:
    (oauth_home / "oauth_token.json").write_text(
        json.dumps(
            {
                "access_token": OAUTH_TOKEN,
                "expires_at": int(time.time() * 1000) - 60_000,
            }
        ),
        encoding="utf-8",
    )
    before = _snapshot(oauth_home)
    route = respx.get("http://127.0.0.1:9/a2a/assets/published-by-me").mock(
        return_value=Response(200, json={"assets": []})
    )
    result = await sync.sync_all(dry_run=True, scope="published")
    assert result["ok"] is False
    assert "OAuth access token" in str(result.get("error") or result.get("errors"))
    assert not route.called
    assert _snapshot(oauth_home) == before


@respx.mock
async def test_sync_dry_run_rejects_missing_auth_before_request(
    oauth_home: Path,
) -> None:
    before = _snapshot(oauth_home)
    route = respx.get("http://127.0.0.1:9/a2a/assets/published-by-me").mock(
        return_value=Response(200, json={"assets": []})
    )
    result = await sync.sync_all(dry_run=True, scope="published")
    assert result["ok"] is False
    assert "OAuth access token" in str(result.get("error") or result.get("errors"))
    assert not route.called
    assert _snapshot(oauth_home) == before
