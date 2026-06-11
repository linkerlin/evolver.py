"""Inbound sync — pull messages from Hub into local store and ACK delivered.

Equivalent to ``evolver/src/proxy/sync/inbound.js``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from evolver.config import HTTP_TRANSPORT_TIMEOUT_MS, resolve_hub_url
from evolver.proxy.lifecycle.manager import AuthError

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_ACTIVE = 10_000
DEFAULT_POLL_INTERVAL_IDLE = 60_000


class InboundSync:
    def __init__(
        self,
        *,
        store: Any,
        hub_url: str | None = None,
        get_headers: Any | None = None,
    ) -> None:
        self._store = store
        self._hub_url = hub_url or resolve_hub_url()
        self._get_headers = get_headers

    async def pull(self, channel: str = "evomap-hub", limit: int = 50) -> dict[str, Any]:
        """Pull inbound messages from the Hub."""
        cursor = self._store.get_cursor(f"cursor:{channel}:inbound_cursor")
        payload = {
            "sender_id": self._store.get_state("node_id"),
            "proxy_protocol_version": "1.0.0",
            "cursor": cursor,
            "limit": limit,
        }

        headers = {"Content-Type": "application/json"}
        if self._get_headers:
            headers.update(self._get_headers())

        try:
            async with httpx.AsyncClient(
                http2=True, timeout=HTTP_TRANSPORT_TIMEOUT_MS / 1000.0
            ) as client:
                response = await client.post(
                    f"{self._hub_url}/v1/a2a/mailbox/inbound",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise AuthError(str(exc), exc.response.status_code)
            return {"received": 0, "error": str(exc)}
        except Exception as exc:
            return {"received": 0, "error": str(exc)}

        messages = body.get("messages", [])
        next_cursor = body.get("next_cursor")

        if messages:
            ids = self._store.write_inbound_batch(messages)
            if next_cursor:
                self._store.set_cursor(f"cursor:{channel}:inbound_cursor", next_cursor)
            return {"received": len(ids), "cursor": next_cursor}
        return {"received": 0}

    async def ack_delivered(self, channel: str = "evomap-hub") -> dict[str, Any]:
        """ACK inbound messages that have been delivered locally."""
        delivered = [
            m.id for m in self._store.list(direction="inbound", status="delivered", limit=1000)
        ]
        if not delivered:
            return {"acked": 0}

        payload = {
            "sender_id": self._store.get_state("node_id"),
            "message_ids": delivered,
        }

        headers = {"Content-Type": "application/json"}
        if self._get_headers:
            headers.update(self._get_headers())

        try:
            async with httpx.AsyncClient(
                http2=True, timeout=HTTP_TRANSPORT_TIMEOUT_MS / 1000.0
            ) as client:
                response = await client.post(
                    f"{self._hub_url}/v1/a2a/mailbox/ack",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise AuthError(str(exc), exc.response.status_code)
            return {"acked": 0, "error": str(exc)}
        except Exception as exc:
            return {"acked": 0, "error": str(exc)}

        return {"acked": len(delivered)}
