"""Tests for evolver.gep.fetch."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import respx
from httpx import Response

from evolver.gep import fetch
from evolver.gep.hub_health import (
    HUB_404_STICKY_THRESHOLD,
    load_state,
    save_state,
)


@respx.mock
async def test_search_assets_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    route = respx.post("https://mock.hub/v1/a2a/search").mock(
        return_value=Response(200, json={"assets": [{"id": "g1", "type": "Gene"}]})
    )
    result = await fetch.search_assets("repair")
    assert result["ok"] is True
    assert len(result["assets"]) == 1
    assert route.called


@respx.mock
async def test_search_assets_no_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch, "get_hub_url", lambda: None)
    result = await fetch.search_assets("repair")
    assert result["ok"] is False
    assert result["error"] == "no_hub_url"


@respx.mock
async def test_download_asset_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    asset = {"id": "g1", "type": "Gene", "category": "repair"}
    respx.post("https://mock.hub/v1/a2a/assets").mock(
        return_value=Response(200, json={"asset": asset})
    )
    # Use a non-sha256 id to skip hash verification
    result = await fetch.download_asset("raw:g1")
    assert result["ok"] is True
    assert result["asset"]["id"] == "g1"


@respx.mock
async def test_download_asset_hash_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    asset = {"id": "g1", "type": "Gene"}
    respx.post("https://mock.hub/v1/a2a/assets").mock(
        return_value=Response(200, json={"asset": asset})
    )
    result = await fetch.download_asset(
        "sha256:0000000000000000000000000000000000000000000000000000000000000000"
    )
    assert result["ok"] is False
    assert result["error"] == "asset_hash_mismatch"


def test_install_gene(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    gene = {"type": "Gene", "id": "g_test", "category": "repair", "signals_match": ["error"]}
    result = fetch.install_gene(gene)
    assert result["ok"] is True
    assert result["gene_id"] == "g_test"


def test_install_gene_rejects_non_gene() -> None:
    result = fetch.install_gene({"type": "Capsule", "id": "c1"})
    assert result["ok"] is False
    assert result["error"] == "not_a_gene"


def test_install_capsule(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    cap = {"type": "Capsule", "id": "c_test", "trigger": ["error"]}
    result = fetch.install_capsule(cap)
    assert result["ok"] is True
    assert result["capsule_id"] == "c_test"


@respx.mock
async def test_fetch_and_install_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    respx.post("https://mock.hub/v1/a2a/search").mock(
        return_value=Response(
            200,
            json={
                "assets": [
                    {"id": "g1", "type": "Gene"},
                    {"id": "c1", "type": "Capsule"},
                ]
            },
        )
    )
    result = await fetch.fetch_and_install("test", dry_run=True)
    assert result["ok"] is True
    assert len(result["installed"]) == 2
    assert result["installed"][0]["action"] == "would_install"


@respx.mock
async def test_search_assets_sticky_skips_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """gene hub_sticky_shared_write: fetch-family call sites honor the shared
    sticky preflight — zero HTTP while the endpoint is stickily missing."""
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    save_state({"consecutive_404": HUB_404_STICKY_THRESHOLD, "last_probe_ts": time.time()})
    result = await fetch.search_assets("repair")  # no routes: HTTP would raise respx
    assert result["ok"] is False
    assert result["error"] == "hub_endpoint_missing"


@respx.mock
async def test_download_asset_404_feeds_counter(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    respx.post("https://mock.hub/v1/a2a/assets").mock(return_value=Response(404))
    result = await fetch.download_asset("raw:g1")
    assert result["ok"] is False
    assert "404" in result["error"]
    assert load_state()["consecutive_404"] == 1, "fetch family 404s count like every consumer's"


@respx.mock
async def test_download_asset_success_resets_counter(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_state({"consecutive_404": HUB_404_STICKY_THRESHOLD - 1, "last_probe_ts": time.time()})
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    asset = {"id": "g1", "type": "Gene", "category": "repair"}
    respx.post("https://mock.hub/v1/a2a/assets").mock(
        return_value=Response(200, json={"asset": asset})
    )
    result = await fetch.download_asset("raw:g1")
    assert result["ok"] is True
    assert load_state()["consecutive_404"] == 0
