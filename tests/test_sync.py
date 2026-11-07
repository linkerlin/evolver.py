"""Tests for evolver.gep.sync."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import respx
from httpx import Response

from evolver.gep import sync
from evolver.gep.hub_health import (
    HUB_404_STICKY_THRESHOLD,
    load_state,
    save_state,
)


@respx.mock
async def test_sync_all_no_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    respx.post("https://mock.hub/v1/a2a/tasks").mock(return_value=Response(200, json={"tasks": []}))
    respx.post("https://mock.hub/v1/a2a/events").mock(
        return_value=Response(200, json={"events": []})
    )
    result = await sync.sync_all(dry_run=True)
    assert result["ok"] is True
    assert result["count"] == 0


@respx.mock
async def test_sync_all_tasks_found(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # dry_run=False installs fetched tasks into the GEP store — without the
    # sandbox this wrote fixture task "t1" into the production store on every
    # full-suite run (round-35, DEBUG #41).
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    respx.post("https://mock.hub/v1/a2a/tasks").mock(
        return_value=Response(200, json={"tasks": [{"task_id": "t1", "title": "Fix bug"}]})
    )
    respx.post("https://mock.hub/v1/a2a/events").mock(
        return_value=Response(200, json={"events": []})
    )
    result = await sync.sync_all(dry_run=False)
    assert result["ok"] is True
    assert any(i.get("id") == "t1" for i in result["installed"])


@respx.mock
async def test_sync_all_events_with_asset(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Same leak class as above: 120 fixture "g1" genes accumulated in the
    # production genes.jsonl overlay before isolation (round-35, DEBUG #41).
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    respx.post("https://mock.hub/v1/a2a/tasks").mock(return_value=Response(200, json={"tasks": []}))
    respx.post("https://mock.hub/v1/a2a/events").mock(
        return_value=Response(200, json={"events": [{"asset_id": "raw:g1", "body": "install g1"}]})
    )
    respx.post("https://mock.hub/v1/a2a/assets").mock(
        return_value=Response(
            200, json={"asset": {"type": "Gene", "id": "g1", "category": "repair"}}
        )
    )
    result = await sync.sync_all(dry_run=False)
    assert result["ok"] is True
    assert any(i.get("id") == "g1" for i in result["installed"])
    installed = (temp_workspace / ".evolver" / "gep" / "genes.jsonl").read_text("utf-8")
    assert '"id": "g1"' in installed, "fixture gene must land in the sandbox store"


@respx.mock
async def test_sync_all_sticky_skips_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """gene hub_sticky_shared_write: while the endpoint is stickily missing,
    manual sync honors the shared preflight — zero HTTP, skip noted."""
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    save_state({"consecutive_404": HUB_404_STICKY_THRESHOLD, "last_probe_ts": time.time()})
    result = await sync.sync_all(dry_run=True)  # no routes registered: any HTTP attempt fails respx
    assert result["ok"] is True
    assert any("hub_endpoint_missing" in e for e in result["errors"])
    assert result["count"] == 0


@respx.mock
async def test_sync_all_404_feeds_shared_counter(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both default-path fetches feed hub_health.record_outcome — a manual
    sync's 404s count toward the sticky threshold like every consumer's."""
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    respx.post("https://mock.hub/v1/a2a/tasks").mock(return_value=Response(404))
    respx.post("https://mock.hub/v1/a2a/events").mock(return_value=Response(404))
    result = await sync.sync_all(dry_run=True)
    assert result["ok"] is True
    assert load_state()["consecutive_404"] == 2, "both fetches observed the 404"


@respx.mock
async def test_sync_all_success_resets_counter(
    temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_state({"consecutive_404": HUB_404_STICKY_THRESHOLD - 1, "last_probe_ts": time.time()})
    monkeypatch.setenv("A2A_HUB_URL", "https://mock.hub")
    respx.post("https://mock.hub/v1/a2a/tasks").mock(return_value=Response(200, json={"tasks": []}))
    respx.post("https://mock.hub/v1/a2a/events").mock(
        return_value=Response(200, json={"events": []})
    )
    result = await sync.sync_all(dry_run=True)
    assert result["ok"] is True
    assert load_state()["consecutive_404"] == 0, "a live endpoint resets the counter"
