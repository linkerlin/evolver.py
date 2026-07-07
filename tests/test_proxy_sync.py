"""Tests for evolver.proxy.sync outbound, inbound, and engine."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from evolver.proxy.lifecycle.manager import AuthError
from evolver.proxy.mailbox.store import MailboxStore
from evolver.proxy.sync.engine import SyncEngine
from evolver.proxy.sync.inbound import InboundSync
from evolver.proxy.sync.outbound import OutboundSync


@pytest.fixture
def store(temp_workspace: Path) -> MailboxStore:
    return MailboxStore(temp_workspace / "mailbox")


# ---------------------------------------------------------------------------
# OutboundSync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outbound_flush_empty(store: MailboxStore) -> None:
    out = OutboundSync(store=store)
    result = await out.flush()
    assert result["sent"] == 0


@pytest.mark.asyncio
async def test_outbound_flush_batch(store: MailboxStore, monkeypatch: pytest.MonkeyPatch) -> None:
    store.send(type="t1", payload={"k": 1})
    store.send(type="t2", payload={"k": 2})

    async def fake_post(*args: Any, **kwargs: Any) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        # Node v1.90.0 semantics: accept every message actually sent in the batch.
        ids = [m["id"] for m in kwargs.get("json", {}).get("messages", [])]
        resp.json.return_value = {"results": [{"id": i, "status": "accepted"} for i in ids]}
        return resp

    monkeypatch.setattr(
        "httpx.AsyncClient.__aenter__", AsyncMock(return_value=MagicMock(post=fake_post))
    )
    monkeypatch.setattr("httpx.AsyncClient.__aexit__", AsyncMock(return_value=False))

    out = OutboundSync(store=store)
    result = await out.flush()
    # Both messages were sent (batch size) and synced (accepted).
    assert result["sent"] == 2
    assert result["synced"] == 2


@pytest.mark.asyncio
async def test_outbound_flush_auth_error(
    store: MailboxStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.send(type="t", payload={})

    async def fake_post(*args: Any, **kwargs: Any) -> MagicMock:
        from httpx import HTTPStatusError, Response

        resp = Response(401, json={"error": "unauthorized"})
        raise HTTPStatusError("401", request=MagicMock(), response=resp)

    monkeypatch.setattr(
        "httpx.AsyncClient.__aenter__", AsyncMock(return_value=MagicMock(post=fake_post))
    )
    monkeypatch.setattr("httpx.AsyncClient.__aexit__", AsyncMock(return_value=False))

    out = OutboundSync(store=store)
    with pytest.raises(AuthError):
        await out.flush()


# ---------------------------------------------------------------------------
# InboundSync
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inbound_pull_empty(store: MailboxStore, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_post(*args: Any, **kwargs: Any) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"messages": []}
        return resp

    monkeypatch.setattr(
        "httpx.AsyncClient.__aenter__", AsyncMock(return_value=MagicMock(post=fake_post))
    )
    monkeypatch.setattr("httpx.AsyncClient.__aexit__", AsyncMock(return_value=False))

    inn = InboundSync(store=store)
    result = await inn.pull()
    assert result["received"] == 0


@pytest.mark.asyncio
async def test_inbound_pull_with_messages(
    store: MailboxStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_post(*args: Any, **kwargs: Any) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "messages": [
                {"id": "hub-1", "type": "notify", "payload": {"x": 1}},
            ],
            "next_cursor": "c2",
        }
        return resp

    monkeypatch.setattr(
        "httpx.AsyncClient.__aenter__", AsyncMock(return_value=MagicMock(post=fake_post))
    )
    monkeypatch.setattr("httpx.AsyncClient.__aexit__", AsyncMock(return_value=False))

    inn = InboundSync(store=store)
    result = await inn.pull()
    assert result["received"] == 1
    assert store.get_by_id("hub-1") is not None


# ---------------------------------------------------------------------------
# SyncEngine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engine_start_stop(store: MailboxStore) -> None:
    engine = SyncEngine(store=store)
    engine.start()
    await asyncio.sleep(0.05)
    assert engine._running is True
    engine.stop()
    await asyncio.sleep(0.05)
    assert engine._running is False


@pytest.mark.asyncio
async def test_engine_notify_accelerates(
    store: MailboxStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = SyncEngine(store=store)
    flushes = 0

    async def counting_flush(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal flushes
        flushes += 1
        return {"sent": 0}

    monkeypatch.setattr(engine._outbound, "flush", counting_flush)
    monkeypatch.setattr(engine._inbound, "pull", AsyncMock(return_value={"received": 0}))
    monkeypatch.setattr(engine._inbound, "ack_delivered", AsyncMock(return_value={"acked": 0}))

    engine.start()
    await asyncio.sleep(0.05)
    engine.notify_new_outbound()
    await asyncio.sleep(0.2)
    engine.stop()
    # At least one flush from the accel path
    assert flushes >= 1
