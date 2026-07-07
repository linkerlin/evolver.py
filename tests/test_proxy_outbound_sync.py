"""Outbound sync v1.90.0 contract tests (G10.9).

Ports ``evolver/test/proxyOutboundSync.test.js``: body-size budgeting, 413
quarantine/back-down, retryable-vs-terminal per-message results, proxy_trace
upload gating, and Hub response-text redaction.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from evolver.proxy.mailbox.store import MailboxStore
from evolver.proxy.sync.outbound import OutboundSync


@pytest.fixture
def store(temp_workspace: Path) -> MailboxStore:
    return MailboxStore(temp_workspace / "mailbox")


def _install_post(monkeypatch: pytest.MonkeyPatch, fake_post: Any) -> list[int]:
    """Patch httpx.AsyncClient to use *fake_post*; return a calls counter list."""
    calls: list[int] = [0]

    async def _wrapped(*args: Any, **kwargs: Any) -> Any:
        calls[0] += 1
        return await fake_post(*args, **kwargs)

    monkeypatch.setattr(
        "httpx.AsyncClient.__aenter__", AsyncMock(return_value=MagicMock(post=_wrapped))
    )
    monkeypatch.setattr("httpx.AsyncClient.__aexit__", AsyncMock(return_value=False))
    return calls


def _ok(body: dict[str, Any]) -> Any:
    req = httpx.Request("POST", "https://hub.example.test/v1/a2a/mailbox/outbound")

    async def fake_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        return httpx.Response(200, json=body, request=req)

    return fake_post


def _raise(status: int, json_body: dict[str, Any] | None = None, text: str = "") -> Any:
    async def fake_post(*_args: Any, **_kwargs: Any) -> httpx.Response:
        resp = httpx.Response(status, json=json_body, text=text)
        raise httpx.HTTPStatusError(f"{status}", request=MagicMock(), response=resp)

    return fake_post


# ---------------------------------------------------------------------------
# Body-size budgeting
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_split_batch_by_body_size(
    store: MailboxStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOMAP_OUTBOUND_SYNC_MAX_BODY_BYTES", "900")
    store.set_state("node_id", "n_split")
    store.send(type="asset_submit", payload={"summary": "a" * 200})
    store.send(type="asset_submit", payload={"summary": "b" * 200})
    store.send(type="asset_submit", payload={"summary": "c" * 200})

    async def fake_post(*_args: Any, **kwargs: Any) -> httpx.Response:
        ids = [m["id"] for m in kwargs["json"]["messages"]]
        req = httpx.Request("POST", "https://hub.example.test/v1/a2a/mailbox/outbound")
        return httpx.Response(
            200, json={"results": [{"id": i, "status": "accepted"} for i in ids]}, request=req
        )

    calls = _install_post(monkeypatch, fake_post)

    result = await OutboundSync(store=store).flush()
    assert result["sent"] == 2
    assert result["synced"] == 2
    assert calls[0] == 1  # one size-bounded batch this flush
    assert store.count_pending(direction="outbound") == 1  # third still pending


@pytest.mark.asyncio
async def test_reject_single_message_over_body_budget(
    store: MailboxStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOMAP_OUTBOUND_SYNC_MAX_BODY_BYTES", "512")
    store.set_state("node_id", "n_big")
    created = store.send(type="asset_submit", payload={"summary": "x" * 2000})

    async def boom(*_args: Any, **_kwargs: Any) -> httpx.Response:
        raise AssertionError("oversized single message should not be sent")

    _install_post(monkeypatch, boom)

    result = await OutboundSync(store=store).flush()
    assert result["sent"] == 0
    assert result["dropped"] == 1
    msg = store.get_by_id(created["message_id"])
    assert msg.status == "rejected"
    assert "exceeds max body bytes" in (msg.error or "")


# ---------------------------------------------------------------------------
# 413 handling
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_413_single_quarantines_and_redacts(
    store: MailboxStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "fake-token-413-abcdefghijklmnopqrstuvwxyz"
    store.set_state("node_id", "n_413_single")
    created = store.send(type="asset_submit", payload={"summary": "hub says too large"})

    _install_post(
        monkeypatch,
        _raise(
            413,
            json_body={
                "error": "entity too large",
                "token": token,
                "authorization": f"Bearer {token}",
            },
        ),
    )

    result = await OutboundSync(store=store).flush()
    assert result["payload_too_large"] is True
    assert result["error"] == "hub_payload_too_large"
    assert result["dropped"] == 1
    msg = store.get_by_id(created["message_id"])
    assert msg.status == "rejected"
    assert "Hub 413 outbound payload too large" in (msg.error or "")
    assert token not in (msg.error or "")  # redacted
    assert store.count_pending(direction="outbound") == 0


@pytest.mark.asyncio
async def test_413_multi_backs_down_budget_leaves_pending(
    store: MailboxStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.set_state("node_id", "n_413_batch")
    store.send(type="asset_submit", payload={"summary": "a" * 1000})
    store.send(type="asset_submit", payload={"summary": "b" * 1000})

    calls = _install_post(monkeypatch, _raise(413, json_body={"error": "entity too large"}))

    result = await OutboundSync(store=store).flush()
    assert result["payload_too_large"] is True
    assert result["error"] == "hub_payload_too_large"
    assert calls[0] == 1
    assert store.count_pending(direction="outbound") == 2  # none rejected
    backed = store.get_state("outbound_sync_max_body_bytes")
    assert isinstance(backed, int) and backed > 0  # budget reduced for next flush


# ---------------------------------------------------------------------------
# Retryable vs terminal per-message results
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_retryable_deferred_without_burning_retry(
    store: MailboxStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.set_state("node_id", "n_retryable")
    created = store.send(type="proxy_trace", priority="low", payload={"trace": "x"})

    _install_post(
        monkeypatch,
        _ok(
            {
                "results": [
                    {
                        "id": created["message_id"],
                        "status": "failed",
                        "reason": "hub overloaded",
                        "retryable": True,
                        "retry_after_ms": 30_000,
                        "terminal": False,
                    }
                ]
            }
        ),
    )

    first = await OutboundSync(store=store).flush()
    deferred = store.get_by_id(created["message_id"])
    assert first["sent"] == 1
    assert first["deferred"] == 1
    assert deferred.status == "pending"
    assert deferred.retry_count == 0
    assert "hub overloaded" in (deferred.error or "")
    assert (deferred.next_retry_at or 0) > int(time.time() * 1000)

    # Second flush must not resend before next_retry_at.
    second = await OutboundSync(store=store).flush()
    assert second["sent"] == 0


@pytest.mark.asyncio
async def test_terminal_finalizes_even_with_retry_hints(
    store: MailboxStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.set_state("node_id", "n_terminal")
    created = store.send(type="proxy_trace", priority="low", payload={"trace": "x"})

    _install_post(
        monkeypatch,
        _ok(
            {
                "results": [
                    {
                        "id": created["message_id"],
                        "status": "failed",
                        "reason": "invalid_proxy_trace_payload_schema",
                        "terminal": True,
                        "retryable": True,  # contradictory: terminal wins
                        "retry_after_ms": 30_000,
                    }
                ]
            }
        ),
    )

    result = await OutboundSync(store=store).flush()
    msg = store.get_by_id(created["message_id"])
    assert result["sent"] == 1
    assert result["synced"] == 1  # terminal counts as removed-from-pending
    assert msg.status == "failed"
    assert msg.retry_count == 0
    assert store.count_pending(direction="outbound") == 0


# ---------------------------------------------------------------------------
# proxy_trace upload gating
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_trace_upload_disabled_drops_proxy_trace(
    store: MailboxStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.set_state("node_id", "n_trace_off")
    store.set_state("trace_collection_enabled", False)
    trace = store.send(type="proxy_trace", priority="low", payload={"trace": "x"})
    asset = store.send(type="asset_submit", payload={"summary": "still send"})

    async def fake_post(*_args: Any, **kwargs: Any) -> httpx.Response:
        ids = [m["id"] for m in kwargs["json"]["messages"]]
        req = httpx.Request("POST", "https://hub.example.test/v1/a2a/mailbox/outbound")
        return httpx.Response(
            200, json={"results": [{"id": i, "status": "accepted"} for i in ids]}, request=req
        )

    _install_post(monkeypatch, fake_post)

    result = await OutboundSync(store=store).flush()
    assert result["dropped"] == 1
    assert result["sent"] == 1
    assert result["synced"] == 1
    assert store.get_by_id(trace["message_id"]).status == "rejected"
    assert store.get_by_id(trace["message_id"]).error == "proxy trace upload disabled"
    assert store.get_by_id(asset["message_id"]).status == "synced"


# ---------------------------------------------------------------------------
# Response-text redaction on whole-batch failure
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_non_2xx_error_text_redacted_before_persist(
    store: MailboxStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "fake-token-500-abcdefghijklmnopqrstuvwxyz"
    store.set_state("node_id", "n_500")
    created = store.send(type="asset_submit", payload={"k": 1})

    _install_post(monkeypatch, _raise(500, json_body={"error": f"Bearer {token} boom"}))

    result = await OutboundSync(store=store).flush()
    msg = store.get_by_id(created["message_id"])
    assert result["sent"] == 0
    assert token not in (result["error"] or "")
    assert token not in (msg.error or "")


# ---------------------------------------------------------------------------
# Store: defer / next_retry_at / poll skip
# ---------------------------------------------------------------------------
def test_defer_sets_backoff_without_burning_retry(store: MailboxStore) -> None:
    created = store.send(type="t", payload={})
    mid = created["message_id"]
    now = int(time.time() * 1000)

    assert store.defer(mid, error="temporary", next_retry_at=now + 60_000) is True
    msg = store.get_by_id(mid)
    assert msg.status == "pending"
    assert msg.retry_count == 0
    assert msg.next_retry_at == now + 60_000
    assert msg.error == "temporary"

    # Deferred-not-due is skipped by poll_outbound.
    assert store.poll_outbound(limit=10) == []
    # Once due (or past), it reappears.
    msg.next_retry_at = now - 1
    assert len(store.poll_outbound(limit=10)) == 1
