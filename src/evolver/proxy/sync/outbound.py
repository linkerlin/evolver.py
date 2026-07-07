"""Outbound sync — push pending messages from local store to Hub.

Equivalent to ``evolver/src/proxy/sync/outbound.js``.

Implements the v1.90.0 outbound contract (ports ``test/proxyOutboundSync.test.js``):

* **Body-size budgeting** — one size-bounded batch per flush
  (``EVOMAP_OUTBOUND_SYNC_MAX_BODY_BYTES`` env, overridable by the store's
  ``outbound_sync_max_body_bytes`` state after a 413 back-down). A single
  message that cannot fit the budget is rejected, not sent.
* **413 handling** — a single-message 413 quarantines that message; a
  multi-message 413 backs the budget down and leaves every message pending.
* **Retryable vs terminal** — a retryable per-message failure is deferred
  (status stays pending, retry count untouched, ``next_retry_at`` set); a
  terminal failure finalises. ``terminal`` wins over retry hints (PR #301).
* **proxy_trace gating** — ``proxy_trace`` messages are dropped when the store
  state ``trace_collection_enabled`` is ``False``.
* **Redaction** — Hub non-2xx response text is redacted before persistence.

Encryption-envelope validation of ``proxy_trace`` payloads is deferred to the
trajectory work (G10.1); see ``TODO.md``.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import httpx

from evolver.config import HTTP_TRANSPORT_TIMEOUT_MS, resolve_hub_url
from evolver.gep.sanitize import redact_string
from evolver.proxy.lifecycle.manager import AuthError

logger = logging.getLogger(__name__)

DEFAULT_OUTBOUND_INTERVAL = 5_000
MAX_BATCH = 50
MAX_RETRIES = 10
DEFAULT_MAX_BODY_BYTES = 1_048_576  # 1 MiB


def _max_body_bytes(store: Any) -> int:
    """Resolve the per-flush body budget.

    Precedence: store state ``outbound_sync_max_body_bytes`` (reduced after a
    413) → ``EVOMAP_OUTBOUND_SYNC_MAX_BODY_BYTES`` env → default.
    """
    state_val = store.get_state("outbound_sync_max_body_bytes")
    if isinstance(state_val, (int, float)) and state_val > 0:
        return int(state_val)
    env_val = os.environ.get("EVOMAP_OUTBOUND_SYNC_MAX_BODY_BYTES") or os.environ.get(
        "EVOLVER_OUTBOUND_SYNC_MAX_BODY_BYTES"
    )
    if env_val:
        try:
            value = int(env_val)
            if value > 0:
                return value
        except ValueError:
            pass
    return DEFAULT_MAX_BODY_BYTES


class OutboundSync:
    """Batch-push pending outbound messages to the Hub with size budgeting."""

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

    def _envelope(self, messages: list[Any]) -> dict[str, Any]:
        return {
            "sender_id": self._store.get_state("node_id"),
            "proxy_protocol_version": "1.0.0",
            "messages": [self._msg_dict(m) for m in messages],
        }

    @staticmethod
    def _msg_dict(m: Any) -> dict[str, Any]:
        return {
            "id": m.id,
            "type": m.type,
            "payload": m.payload,
            "priority": m.priority,
            "ref_id": m.ref_id,
            "created_at": m.created_at,
        }

    async def flush(self, channel: str = "evomap-hub") -> dict[str, Any]:  # noqa: PLR0911, PLR0912, PLR0915
        """Flush one size-bounded batch of pending outbound messages."""
        result: dict[str, Any] = {
            "sent": 0,
            "synced": 0,
            "dropped": 0,
            "deferred": 0,
            "payload_too_large": False,
            "error": None,
            "responses": [],
        }
        pending = self._store.poll_outbound(channel=channel, limit=MAX_BATCH)
        if not pending:
            return result

        # Gate proxy_trace upload on the trace_collection_enabled store state.
        trace_enabled = self._store.get_state("trace_collection_enabled")
        eligible: list[Any] = []
        for m in pending:
            if m.type == "proxy_trace" and trace_enabled is False:
                self._store.update_status(m.id, "rejected", error="proxy trace upload disabled")
                result["dropped"] += 1
                continue
            eligible.append(m)
        if not eligible:
            return result

        budget = _max_body_bytes(self._store)
        envelope_overhead = len(json.dumps(self._envelope([])).encode())

        # Build ONE size-bounded batch; reject oversized singles, leave the rest
        # pending for the next flush.
        batch: list[Any] = []
        for m in eligible:
            msg_size = len(json.dumps(self._msg_dict(m)).encode())
            if envelope_overhead + msg_size > budget:
                self._store.update_status(
                    m.id,
                    "rejected",
                    error=f"message {msg_size}B exceeds max body bytes {budget}",
                )
                result["dropped"] += 1
                continue
            current_size = (
                len(json.dumps(self._envelope(batch)).encode()) if batch else envelope_overhead
            )
            # ponytail: +2 approximates the ", " separator between JSON messages.
            if batch and current_size + msg_size + 2 > budget:
                break
            batch.append(m)

        if not batch:
            return result

        payload = self._envelope(batch)
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
            status = exc.response.status_code
            if status in (401, 403):
                raise AuthError(str(exc), status) from exc
            redacted = redact_string(exc.response.text)
            if status == 413:
                result["payload_too_large"] = True
                result["error"] = "hub_payload_too_large"
                if len(batch) == 1:
                    self._store.update_status(
                        batch[0].id,
                        "rejected",
                        error=f"Hub 413 outbound payload too large: {redacted}",
                    )
                    result["dropped"] += 1
                else:
                    # Back the budget down for future flushes; leave all pending.
                    self._store.set_state("outbound_sync_max_body_bytes", max(budget // 2, 1))
                return result
            # Other HTTP error: whole-batch failure; sanitize before persist.
            for m in batch:
                self._store.increment_retry(m.id, error=redacted)
            result["error"] = redacted
            return result
        except Exception as exc:
            err = redact_string(str(exc))
            for m in batch:
                self._store.increment_retry(m.id, error=err)
            result["error"] = err
            return result

        # 200 OK: per-message result processing.
        now_ms = int(time.time() * 1000)
        result["sent"] = len(batch)
        responses: list[dict[str, Any]] = []
        for item in body.get("results", []):
            msg_id = item.get("id")
            status = item.get("status")
            reason = redact_string(str(item.get("reason") or item.get("error") or ""))
            terminal = bool(item.get("terminal"))
            retryable = bool(item.get("retryable"))
            retry_after_ms = int(item.get("retry_after_ms") or 0)

            if status in ("accepted", "ok"):
                self._store.update_status(msg_id, "synced", synced_at=now_ms)
                result["synced"] += 1
            elif terminal:
                # Terminal wins over retry hints (PR #301): finalise, do not defer.
                self._store.update_status(msg_id, "failed", error=reason)
                result["synced"] += 1
            elif retryable:
                self._store.defer(msg_id, error=reason, next_retry_at=now_ms + retry_after_ms)
                result["deferred"] += 1
            elif status in ("failed", "rejected"):
                retry = self._store.get_by_id(msg_id)
                if retry and retry.retry_count < MAX_RETRIES:
                    self._store.increment_retry(msg_id, error=reason)
                else:
                    self._store.update_status(msg_id, "failed", error=reason)
            if item.get("response"):
                responses.append(item)
        result["responses"] = responses
        return result
