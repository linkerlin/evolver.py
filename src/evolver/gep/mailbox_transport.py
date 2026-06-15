"""Mailbox transport — send/receive/list messages via the local proxy.

Equivalent to ``evolver/src/gep/mailboxTransport.js`` (108 lines).

Provides a thin client for the local A2A Proxy's mailbox API
(``/v1/a2a/mailbox/*``). If the proxy is not running, it can be started
automatically. Used by session hooks and the evolution pipeline to
communicate with the Hub without a direct connection.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from typing import Any

import httpx

from evolver.config import resolve_proxy_port

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 10.0


def _proxy_base_url() -> str:
    port = resolve_proxy_port()
    return f"http://127.0.0.1:{port}/v1/a2a"


def _is_proxy_running() -> bool:
    """Check if the local proxy is accepting connections."""
    try:
        resp = httpx.get(f"{_proxy_base_url()}/proxy/status", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


def ensure_proxy_alive(*, auto_start: bool = True) -> bool:
    """Ensure the local proxy is running. Optionally start it if not.

    Returns True if the proxy is (or was successfully started) running.
    """
    if _is_proxy_running():
        return True
    if not auto_start:
        return False
    # Best-effort start via CLI subprocess (fire-and-forget).
    try:
        subprocess.Popen(
            [sys.executable, "-m", "evolver", "proxy"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "EVOLVER_PROXY_DAEMON": "1"},
        )
        # Wait briefly for startup.
        for _ in range(10):
            time.sleep(0.5)
            if _is_proxy_running():
                return True
    except Exception as exc:
        logger.warning("[mailbox_transport] Failed to start proxy: %s", exc)
    return False


async def send_message(
    msg_type: str,
    payload: dict[str, Any],
    *,
    recipient: str = "",
) -> dict[str, Any]:
    """Send a message via the proxy mailbox."""
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.post(
            f"{_proxy_base_url()}/mailbox/send",
            json={"type": msg_type, "payload": payload, "recipient": recipient},
        )
        ok = resp.status_code == 200
        return {"ok": ok, "data": resp.json() if ok else None}


async def poll_messages(
    *,
    msg_type: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Poll for new messages from the proxy mailbox."""
    params: dict[str, Any] = {"limit": limit}
    if msg_type:
        params["type"] = msg_type
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.post(
            f"{_proxy_base_url()}/mailbox/poll",
            json=params,
        )
        ok = resp.status_code == 200
        return {"ok": ok, "data": resp.json() if ok else None}


async def ack_messages(msg_ids: list[str]) -> dict[str, Any]:
    """Acknowledge (mark as processed) a batch of messages."""
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.post(
            f"{_proxy_base_url()}/mailbox/ack",
            json={"msg_ids": msg_ids},
        )
        ok = resp.status_code == 200
        count = resp.json().get("acked", 0) if ok else 0
        return {"ok": ok, "count": count}


async def list_messages(
    *,
    msg_type: str | None = None,
    status: str = "all",
) -> dict[str, Any]:
    """List messages from the proxy mailbox."""
    params: dict[str, str] = {"status": status}
    if msg_type:
        params["type"] = msg_type
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.get(
            f"{_proxy_base_url()}/mailbox/list",
            params=params,
        )
        ok = resp.status_code == 200
        return {"ok": ok, "data": resp.json() if ok else None}


__all__ = [
    "ack_messages",
    "ensure_proxy_alive",
    "list_messages",
    "poll_messages",
    "send_message",
]
