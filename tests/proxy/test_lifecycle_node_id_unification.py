"""Lifecycle node_id unification (proxy ↔ legacy ~/.evomap/node_id).

Ports core contracts from Node ``lifecycleNodeIdUnification.test.js``:
constructor early-persist, hello mint/reuse/store-wins, short suffix guards.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from evolver.gep import node_identity as ni
from evolver.proxy.lifecycle.manager import LifecycleManager
from evolver.proxy.mailbox.store import MailboxStore

STORE_ID = "node_973fad206a3846f7"
LEGACY_ID = "node_abcdef0123456789"


@pytest.fixture
def evomap_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "evomap"
    home.mkdir()
    monkeypatch.setenv("EVOLVER_HOME", str(home))
    monkeypatch.delenv("A2A_NODE_ID", raising=False)
    ni.reset_cached_node_id()
    yield home
    ni.reset_cached_node_id()


@pytest.fixture
def store(evomap_home: Path) -> MailboxStore:
    return MailboxStore(evomap_home / "mailbox")


def _mock_hello_ok(monkeypatch: pytest.MonkeyPatch, body: dict[str, Any] | None = None) -> None:
    payload = body or {"payload": {"status": "acknowledged"}}

    async def fake_post(*_a: Any, **_k: Any) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = payload
        return resp

    client = MagicMock()
    client.post = AsyncMock(side_effect=fake_post)
    monkeypatch.setattr("httpx.AsyncClient.__aenter__", AsyncMock(return_value=client))
    monkeypatch.setattr("httpx.AsyncClient.__aexit__", AsyncMock(return_value=False))


def test_constructor_persists_store_node_id_before_hello(
    evomap_home: Path, store: MailboxStore
) -> None:
    legacy = evomap_home / "node_id"
    assert not legacy.exists()
    store.set_state("node_id", STORE_ID)
    LifecycleManager(store=store, version="1.0.0")
    assert legacy.exists()
    assert legacy.read_text(encoding="utf-8").strip() == STORE_ID


def test_constructor_rejects_malformed_store_node_id(
    evomap_home: Path, store: MailboxStore
) -> None:
    store.set_state("node_id", "not_a_valid_node_id")
    LifecycleManager(store=store, version="1.0.0")
    assert not (evomap_home / "node_id").exists()


def test_pre_hello_short_suffix_not_anon(evomap_home: Path, store: MailboxStore) -> None:
    store.set_state("node_id", STORE_ID)
    LifecycleManager(store=store, version="1.0.0")
    expected = STORE_ID.removeprefix("node_")[:8]
    assert ni.short_node_id_for_state_path() == expected
    assert expected != "anon"
    path = ni.force_update_last_state_path()
    assert path.name == f"force_update_last.{expected}.json"
    assert path.parent == evomap_home


@pytest.mark.asyncio
async def test_hello_fresh_install_mints_and_persists(
    evomap_home: Path, store: MailboxStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("A2A_NODE_SECRET", "a" * 64)
    _mock_hello_ok(monkeypatch)
    mgr = LifecycleManager(store=store, version="1.0.0")
    result = await mgr.hello()
    assert result["ok"] is True
    node_id = result["nodeId"]
    assert ni.is_valid_node_id(node_id)
    assert (evomap_home / "node_id").read_text(encoding="utf-8").strip() == node_id
    assert store.get_state("node_id") == node_id
    assert mgr.nodeId == node_id


@pytest.mark.asyncio
async def test_hello_reuses_legacy_id(
    evomap_home: Path, store: MailboxStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("A2A_NODE_SECRET", "a" * 64)
    (evomap_home / "node_id").write_text(LEGACY_ID, encoding="utf-8")
    seen: dict[str, Any] = {}

    async def fake_post(*_a: Any, **kwargs: Any) -> MagicMock:
        seen["json"] = kwargs.get("json")
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"payload": {"status": "acknowledged"}}
        return resp

    client = MagicMock()
    client.post = AsyncMock(side_effect=fake_post)
    monkeypatch.setattr("httpx.AsyncClient.__aenter__", AsyncMock(return_value=client))
    monkeypatch.setattr("httpx.AsyncClient.__aexit__", AsyncMock(return_value=False))

    mgr = LifecycleManager(store=store, version="1.0.0")
    result = await mgr.hello()
    assert result["nodeId"] == LEGACY_ID
    assert seen["json"]["sender_id"] == LEGACY_ID
    assert (evomap_home / "node_id").read_text(encoding="utf-8").strip() == LEGACY_ID


@pytest.mark.asyncio
async def test_hello_store_wins_overwrites_legacy(
    evomap_home: Path, store: MailboxStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("A2A_NODE_SECRET", "a" * 64)
    (evomap_home / "node_id").write_text(LEGACY_ID, encoding="utf-8")
    store.set_state("node_id", STORE_ID)
    _mock_hello_ok(monkeypatch)
    mgr = LifecycleManager(store=store, version="1.0.0")
    result = await mgr.hello()
    assert result["nodeId"] == STORE_ID
    assert (evomap_home / "node_id").read_text(encoding="utf-8").strip() == STORE_ID


@pytest.mark.asyncio
async def test_store_wins_clears_canonical_credentials(
    evomap_home: Path, store: MailboxStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("A2A_NODE_SECRET", "a" * 64)
    (evomap_home / "node_id").write_text(LEGACY_ID, encoding="utf-8")
    (evomap_home / "node_secret").write_text("a" * 64, encoding="utf-8")
    (evomap_home / "node_secret_version").write_text("7", encoding="utf-8")
    (evomap_home / "node_secret_source").write_text("hub_rotate", encoding="utf-8")
    store.set_state("node_id", STORE_ID)
    _mock_hello_ok(monkeypatch)
    mgr = LifecycleManager(store=store, version="1.0.0")
    await mgr.hello()
    assert (evomap_home / "node_id").read_text(encoding="utf-8").strip() == STORE_ID
    assert not (evomap_home / "node_secret").exists()
    assert not (evomap_home / "node_secret_version").exists()
    assert not (evomap_home / "node_secret_source").exists()


def test_short_suffix_rejects_path_traversal(evomap_home: Path) -> None:
    (evomap_home / "node_id").write_text("node_../etc/passwd", encoding="utf-8")
    ni.reset_cached_node_id()
    assert ni.short_node_id_for_state_path() == "anon"
    path = ni.force_update_last_state_path()
    assert path.parent == evomap_home
    assert path.name == "force_update_last.anon.json"


def test_short_suffix_rejects_uppercase_hex(evomap_home: Path) -> None:
    (evomap_home / "node_id").write_text("node_ABCDEF0123456789", encoding="utf-8")
    ni.reset_cached_node_id()
    assert ni.short_node_id_for_state_path() == "anon"


def test_on_delivery_identity_change_unsubscribe(store: MailboxStore) -> None:
    mgr = LifecycleManager(store=store, version="1.0.0")
    hits: list[int] = []
    unsub = mgr.on_delivery_identity_change(lambda: hits.append(1))
    mgr._notify_delivery_identity_change()
    assert hits == [1]
    unsub()
    mgr._notify_delivery_identity_change()
    assert hits == [1]
