"""Outbound sync — push pending messages from local store to Hub.

Equivalent to ``evolver/src/proxy/sync/outbound.js``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from evolver.config import HTTP_TRANSPORT_TIMEOUT_MS, resolve_hub_url
from evolver.proxy.lifecycle.manager import AuthError

logger = logging.getLogger(__name__)

DEFAULT_OUTBOUND_INTERVAL = 5_000
MAX_BATCH = 50
MAX_RETRIES = 10


class OutboundSync:
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

    async def flush(self, channel: str = "evomap-hub") -> dict[str, Any]:
        """Batch-push pending outbound messages to the Hub."""
        messages = self._store.poll_outbound(channel=channel, limit=MAX_BATCH)
        if not messages:
            return {"sent": 0}

        payload_messages = [
            {
                "id": m.id,
                "type": m.type,
                "payload": m.payload,
                "priority": m.priority,
                "ref_id": m.ref_id,
                "created_at": m.created_at,
            }
            for m in messages
        ]

        payload = {
            "sender_id": self._store.get_state("node_id"),
            "proxy_protocol_version": "1.0.0",
            "messages": payload_messages,
        }

        headers = {"Content-Type": "application/json"}
        if self._get_headers:
            headers.update(self._get_headers())

        try:
            async with httpx.AsyncClient(
                http2=True, timeout=HTTP_TRANSPORT_TIMEOUT_MS / 1000.0
            ) as client:
                response = await client.post(
                    f"{self._hub_url}/v1/a2a/mailbox/outbound",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise AuthError(str(exc), exc.response.status_code)
            # Whole-batch failure: increment retry for all
            for m in messages:
                self._store.increment_retry(m.id, error=str(exc))
            return {"sent": 0, "error": str(exc)}
        except Exception as exc:
            for m in messages:
                self._store.increment_retry(m.id, error=str(exc))
            return {"sent": 0, "error": str(exc)}

        # Per-message result processing
        results = body.get("results", [])
        sent = 0
        responses: list[dict[str, Any]] = []

        for item in results:
            msg_id = item.get("id")
            status = item.get("status")
            if status in ("accepted", "ok"):
                self._store.update_status(msg_id, "synced", synced_at=int(__import__("time").time() * 1000))
                sent += 1
            elif status in ("failed", "rejected"):
                retry = self._store.get_by_id(msg_id)
                if retry and retry.retry_count < MAX_RETRIES:
                    self._store.increment_retry(msg_id, error=item.get("error"))
                else:
                    self._store.update_status(msg_id, "failed", error=item.get("error"))
            if item.get("response"):
                responses.append(item)

        return {"sent": sent, "responses": responses}
