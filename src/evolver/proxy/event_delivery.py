"""Hub event delivery: SSE + poll fallback with identity-aware auth.

Behaviourally aligned with Node ``a2aProtocol`` event-delivery ownership
(v1.92.0): accepted events are de-duplicated by id, handed to a mailbox
bridge exactly once, and transport re-binds when the delivery identity
changes. Packaged SSE fetch never reads host browser credentials — only
the identity provider / node secret headers.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

# Wall-clock jump larger than this (seconds) triggers SSE reset + poll restore.
WALL_CLOCK_DRIFT_S = 90.0
DEFAULT_POLL_MS = 15_000
HUB_EVENT_RETRY_BASE_MS = 100


@dataclass
class IdentityProvider:
    """Supplies live node id / headers and identity-change subscriptions."""

    get_node_id: Callable[[], str | None]
    get_headers: Callable[[], dict[str, str]]
    subscribe: Callable[[Callable[[], None]], Callable[[], None]] | None = None


@dataclass
class _DeliveryState:
    accepted_ids: set[str] = field(default_factory=set)
    self_driving_poll_enabled: bool = True
    sse_healthy: bool = False
    running: bool = False
    hub_url: str = ""
    enable_sse: bool = True
    last_wall_clock: float = field(default_factory=time.time)


class HubEventBridge:
    """Accept Hub events into the local mailbox exactly once.

    On transient write failure, retries locally once (no second Hub delivery).
    Extension handlers run only after a successful write.
    """

    def __init__(
        self,
        *,
        store: Any,
        on_inbound: Callable[[], None] | None = None,
        retry_base_ms: int = HUB_EVENT_RETRY_BASE_MS,
    ) -> None:
        self._store = store
        self._on_inbound = on_inbound
        self._retry_base_ms = retry_base_ms
        self._pending: dict[str, dict[str, Any]] = {}
        self._retry_task: asyncio.Task[None] | None = None
        self._stopped = False

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def accept_hub_events(self, events: list[dict[str, Any]]) -> int:
        """Write *events* to mailbox; return number of newly inserted ids."""
        if self._stopped:
            return 0
        inserted = 0
        for event in events:
            if not isinstance(event, dict):
                continue
            event_id = event.get("id")
            if not event_id or not isinstance(event_id, str):
                continue
            if self._store.get_by_id(event_id) is not None:
                continue
            if event_id in self._pending:
                continue
            try:
                self._write_and_apply(event)
                inserted += 1
            except Exception as exc:
                logger.debug("[HubEventBridge] write failed for %s: %s", event_id, exc)
                self._pending[event_id] = event
                self._schedule_retry()
        return inserted

    def _write_and_apply(self, event: dict[str, Any]) -> None:
        event_id = str(event["id"])
        event_type = str(event.get("type") or "hub_event")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        self._store.write_inbound(id=event_id, type=event_type, payload=payload)
        # Mark delivered so poll() no longer surfaces it as pending work.
        self._store.ack([event_id])
        self._apply_extension(event)
        if self._on_inbound is not None:
            self._on_inbound()

    def _apply_extension(self, event: dict[str, Any]) -> None:
        """Apply well-known Hub control events to local store state."""
        event_type = event.get("type")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event_type == "trace_collection_config":
            enabled = payload.get("enabled")
            if enabled is not None:
                self._store.set_state(
                    "trace_collection_enabled",
                    "true" if enabled else "false",
                )

    def _schedule_retry(self) -> None:
        if self._stopped:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Sync context: best-effort immediate single retry.
            self._retry_pending_once()
            return
        if self._retry_task is not None and not self._retry_task.done():
            return
        self._retry_task = loop.create_task(self._retry_after_delay())

    async def _retry_after_delay(self) -> None:
        await asyncio.sleep(self._retry_base_ms / 1000.0)
        if self._stopped:
            return
        self._retry_pending_once()

    def _retry_pending_once(self) -> None:
        if not self._pending:
            return
        remaining: dict[str, dict[str, Any]] = {}
        for event_id, event in list(self._pending.items()):
            if self._store.get_by_id(event_id) is not None:
                continue
            try:
                self._write_and_apply(event)
            except Exception:
                remaining[event_id] = event
        self._pending = remaining
        if self._pending and not self._stopped:
            self._schedule_retry()

    def stop(self) -> None:
        self._stopped = True
        self._pending.clear()
        if self._retry_task is not None:
            self._retry_task.cancel()
            self._retry_task = None


class EventDeliveryManager:
    """Owns Hub SSE + poll delivery for a single process.

    Public test hooks mirror Node ``protocol._testing`` surface used by
    proxyEventDeliveryBridge / dynamicIdentity contracts.
    """

    def __init__(self) -> None:
        self._state = _DeliveryState()
        self._identity: IdentityProvider | None = None
        self._on_events_accepted: Callable[[list[dict[str, Any]]], int | None] | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._sse_task: asyncio.Task[None] | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._drift_task: asyncio.Task[None] | None = None
        self._sse_client: httpx.AsyncClient | None = None
        self._fallback_node_id: str = ""

    # --- Test-facing buffer API ---

    def reset_hub_event_buffer(self) -> None:
        self._state.accepted_ids.clear()

    def buffer_polled_hub_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Accept new events by id; invoke on_events_accepted once per new id."""
        fresh: list[dict[str, Any]] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            event_id = event.get("id")
            if not event_id or not isinstance(event_id, str):
                continue
            if event_id in self._state.accepted_ids:
                continue
            self._state.accepted_ids.add(event_id)
            fresh.append(event)
        if fresh and self._on_events_accepted is not None:
            self._on_events_accepted(fresh)
        return fresh

    def get_internals(self) -> dict[str, Any]:
        return {
            "selfDrivingPollEnabled": self._state.self_driving_poll_enabled,
            "sseHealthy": self._state.sse_healthy,
            "running": self._state.running,
            "hasSelfDrivingPollTimer": self._poll_task is not None
            and not (self._poll_task.done() if self._poll_task else True),
            "acceptedCount": len(self._state.accepted_ids),
        }

    # --- Lifecycle ---

    def start(
        self,
        *,
        hub_url: str = "",
        node_id: str = "",
        enable_sse: bool = True,
        identity_provider: IdentityProvider | dict[str, Any] | None = None,
        on_events_accepted: Callable[[list[dict[str, Any]]], int | None] | None = None,
    ) -> None:
        """Start or replace event delivery ownership."""
        self.stop()
        self._state = _DeliveryState(
            hub_url=(hub_url or "").rstrip("/"),
            enable_sse=enable_sse,
            running=True,
            last_wall_clock=time.time(),
        )
        self._fallback_node_id = node_id or ""
        self._on_events_accepted = on_events_accepted
        self._identity = self._normalize_identity(identity_provider)

        if self._identity and self._identity.subscribe:
            self._unsubscribe = self._identity.subscribe(self._on_identity_change)

        if not self._state.hub_url:
            # Offline / bridge-only mode: buffer API still works.
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("[EventDelivery] no running loop; transport deferred")
            return

        if enable_sse:
            self._sse_task = loop.create_task(self._sse_loop())
        self._poll_task = loop.create_task(self._poll_loop())
        self._drift_task = loop.create_task(self._drift_loop())

    def stop(self) -> None:
        self._state.running = False
        self._state.sse_healthy = False
        if self._unsubscribe is not None:
            with contextlib.suppress(Exception):
                self._unsubscribe()
            self._unsubscribe = None
        for task in (self._sse_task, self._poll_task, self._drift_task):
            if task is not None:
                task.cancel()
        self._sse_task = self._poll_task = self._drift_task = None
        if self._sse_client is not None:
            # Client closed in SSE loop finally; drop reference.
            self._sse_client = None
        self._identity = None

    def recover_after_wake(self) -> None:
        """Wall-clock wake: close SSE and re-enable self-driving poll."""
        self._state.sse_healthy = False
        self._state.self_driving_poll_enabled = True
        if self._sse_task is not None:
            self._sse_task.cancel()
            self._sse_task = None
        try:
            loop = asyncio.get_running_loop()
            if self._state.running and self._state.enable_sse and self._state.hub_url:
                self._sse_task = loop.create_task(self._sse_loop())
            if self._state.running and (self._poll_task is None or self._poll_task.done()):
                self._poll_task = loop.create_task(self._poll_loop())
        except RuntimeError:
            pass

    def _normalize_identity(
        self, provider: IdentityProvider | dict[str, Any] | None
    ) -> IdentityProvider | None:
        if provider is None:
            return None
        if isinstance(provider, IdentityProvider):
            return provider
        if isinstance(provider, dict):
            return IdentityProvider(
                get_node_id=provider.get("getNodeId")
                or provider.get("get_node_id")
                or (lambda: None),
                get_headers=provider.get("getHeaders")
                or provider.get("get_headers")
                or (lambda: {}),
                subscribe=provider.get("subscribe"),
            )
        return None

    def _resolve_node_id(self) -> str | None:
        if self._identity is not None:
            try:
                nid = self._identity.get_node_id()
                if nid:
                    return str(nid)
            except Exception:
                pass
        return self._fallback_node_id or None

    def _resolve_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "text/event-stream"}
        if self._identity is not None:
            try:
                extra = self._identity.get_headers() or {}
                headers.update({str(k): str(v) for k, v in extra.items()})
            except Exception:
                pass
        return headers

    def _on_identity_change(self) -> None:
        """Rebind transport when node secret / id rotates."""
        if not self._state.running:
            return
        # Same-node secret rotation: keep SSE if healthy; just refresh next request headers.
        # Full node_id change restarts SSE.
        nid = self._resolve_node_id()
        if nid is None:
            # Not registered yet — pause delivery.
            self._state.sse_healthy = False
            if self._sse_task is not None:
                self._sse_task.cancel()
                self._sse_task = None
            return
        if self._sse_task is not None and not self._state.sse_healthy:
            self._sse_task.cancel()
            self._sse_task = None
            try:
                loop = asyncio.get_running_loop()
                if self._state.enable_sse:
                    self._sse_task = loop.create_task(self._sse_loop())
            except RuntimeError:
                pass

    def stream_url(self, *, node_id: str | None = None, duration_ms: int | None = None) -> str:
        """Build SSE URL (issue600: no host credentials in query)."""
        base = self._state.hub_url.rstrip("/")
        nid = node_id or self._resolve_node_id() or ""
        params: dict[str, str] = {}
        if nid:
            params["node_id"] = nid
        if duration_ms is not None:
            params["duration_ms"] = str(duration_ms)
        qs = urlencode(params)
        path = f"{base}/a2a/events/stream"
        return f"{path}?{qs}" if qs else path

    async def open_event_stream(
        self,
        *,
        node_id: str | None = None,
        duration_ms: int | None = None,
    ) -> dict[str, Any]:
        """Open SSE via httpx (packaged fetch — Authorization from identity only)."""
        if not self._state.hub_url and not node_id:
            # Allow explicit hub from identity headers context only when set.
            pass
        url = self.stream_url(node_id=node_id, duration_ms=duration_ms)
        headers = self._resolve_headers()
        headers.setdefault("Accept", "text/event-stream")
        client = httpx.AsyncClient(http2=True, timeout=None)
        try:
            request = client.build_request("GET", url, headers=headers)
            response = await client.send(request, stream=True)
            if response.status_code >= 400:
                await response.aclose()
                await client.aclose()
                return {"ok": False, "error": f"status_{response.status_code}"}

            close_holder: dict[str, asyncio.Task[None] | None] = {"task": None}

            def close() -> None:
                try:
                    loop = asyncio.get_running_loop()
                    close_holder["task"] = loop.create_task(self._close_stream(response, client))
                except RuntimeError:
                    pass

            return {
                "ok": True,
                "url": url,
                "headers": headers,
                "close": close,
                "response": response,
            }
        except Exception as exc:
            await client.aclose()
            return {"ok": False, "error": str(exc)}

    async def _close_stream(self, response: httpx.Response, client: httpx.AsyncClient) -> None:
        with contextlib.suppress(Exception):
            await response.aclose()
        with contextlib.suppress(Exception):
            await client.aclose()

    async def _sse_loop(self) -> None:
        while self._state.running:
            nid = self._resolve_node_id()
            if not nid:
                await asyncio.sleep(0.5)
                continue
            url = self.stream_url(node_id=nid)
            headers = self._resolve_headers()
            headers.setdefault("Accept", "text/event-stream")
            try:
                async with httpx.AsyncClient(http2=True, timeout=None) as client:
                    self._sse_client = client
                    async with client.stream("GET", url, headers=headers) as response:
                        if response.status_code >= 400:
                            self._state.sse_healthy = False
                            self._state.self_driving_poll_enabled = True
                            await asyncio.sleep(1.0)
                            continue
                        self._state.sse_healthy = True
                        # Healthy SSE suppresses persistent long-poll.
                        self._state.self_driving_poll_enabled = False
                        async for line in response.aiter_lines():
                            if not self._state.running:
                                break
                            self._handle_sse_line(line)
                        # Stream ended (server closed / finite body) — fall back to poll.
                        self._state.sse_healthy = False
                        self._state.self_driving_poll_enabled = True
                        if not self._state.running:
                            return
                        await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("[EventDelivery] SSE error: %s", exc)
                self._state.sse_healthy = False
                self._state.self_driving_poll_enabled = True
                await asyncio.sleep(1.0)
            finally:
                self._sse_client = None

    def _handle_sse_line(self, line: str) -> None:
        if not line.startswith("data:"):
            return
        raw = line[5:].strip()
        if not raw:
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if isinstance(data, dict):
            if "id" not in data and data.get("type"):
                data = {
                    "id": f"sse_{int(time.time() * 1000)}_{data.get('type')}",
                    "type": data.get("type"),
                    "payload": data.get("payload") or data,
                }
            self.buffer_polled_hub_events([data])

    async def _poll_loop(self) -> None:
        while self._state.running:
            if not self._state.self_driving_poll_enabled:
                await asyncio.sleep(0.5)
                continue
            nid = self._resolve_node_id()
            if not nid or not self._state.hub_url:
                await asyncio.sleep(0.5)
                continue
            wait_ms = await self._run_poll_once()
            await asyncio.sleep(max(wait_ms, 100) / 1000.0)

    async def _run_poll_once(self) -> int:
        """Single poll tick (exposed for tests)."""
        nid = self._resolve_node_id()
        if not nid or not self._state.hub_url:
            return DEFAULT_POLL_MS
        url = f"{self._state.hub_url}/a2a/events/poll"
        headers = self._resolve_headers()
        headers["Content-Type"] = "application/json"
        headers.pop("Accept", None)
        payload = {"sender_id": nid}
        try:
            async with httpx.AsyncClient(http2=True, timeout=30.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code >= 400:
                    return DEFAULT_POLL_MS
                body = response.json()
        except Exception as exc:
            logger.debug("[EventDelivery] poll error: %s", exc)
            return DEFAULT_POLL_MS
        events = body.get("events") if isinstance(body, dict) else None
        if isinstance(events, list):
            self.buffer_polled_hub_events([e for e in events if isinstance(e, dict)])
        next_ms = body.get("next_poll_after_ms") if isinstance(body, dict) else None
        try:
            return int(next_ms) if next_ms is not None else DEFAULT_POLL_MS
        except (TypeError, ValueError):
            return DEFAULT_POLL_MS

    async def run_self_driving_poll_for_testing(self) -> int:
        return await self._run_poll_once()

    async def _drift_loop(self) -> None:
        while self._state.running:
            await asyncio.sleep(1.0)
            now = time.time()
            if now - self._state.last_wall_clock > WALL_CLOCK_DRIFT_S:
                logger.info("[EventDelivery] wall-clock drift detected; recovering")
                self.recover_after_wake()
            self._state.last_wall_clock = now


# Process-wide singleton (Node module-level event delivery ownership).
_manager = EventDeliveryManager()


def start_event_delivery(**kwargs: Any) -> None:
    _manager.start(**kwargs)


def stop_event_delivery() -> None:
    _manager.stop()


def buffer_polled_hub_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _manager.buffer_polled_hub_events(events)


def reset_hub_event_buffer() -> None:
    _manager.reset_hub_event_buffer()


def get_event_delivery_internals() -> dict[str, Any]:
    return _manager.get_internals()


def recover_event_delivery_after_wake() -> None:
    _manager.recover_after_wake()


def get_event_delivery_manager() -> EventDeliveryManager:
    return _manager


async def hub_open_event_stream(
    *,
    hub_url: str,
    node_id: str,
    duration_ms: int | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Open a Hub SSE stream using only explicit headers (issue #600)."""
    mgr = EventDeliveryManager()
    mgr._state.hub_url = hub_url.rstrip("/")
    mgr._state.running = True
    if headers:

        def _headers() -> dict[str, str]:
            return dict(headers)

        mgr._identity = IdentityProvider(get_node_id=lambda: node_id, get_headers=_headers)
    return await mgr.open_event_stream(node_id=node_id, duration_ms=duration_ms)


__all__ = [
    "EventDeliveryManager",
    "HubEventBridge",
    "IdentityProvider",
    "buffer_polled_hub_events",
    "get_event_delivery_internals",
    "get_event_delivery_manager",
    "hub_open_event_stream",
    "recover_event_delivery_after_wake",
    "reset_hub_event_buffer",
    "start_event_delivery",
    "stop_event_delivery",
]
