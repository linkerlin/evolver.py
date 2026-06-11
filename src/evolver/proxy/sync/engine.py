"""Sync engine — coordinates outbound and inbound sync loops.

Equivalent to ``evolver/src/proxy/sync/engine.js``.
Runs two independent timer-driven loops and handles idle/active
poll-interval adaptation.

Design notes (Pythonic)
-----------------------
* Each loop is a cancellable ``asyncio.Task``.
* Defensive ``try/except`` around every tick ensures a single failure never
  kills the supervisor.
* ``notify_new_outbound()`` accelerates the next flush to 100 ms.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from evolver.proxy.lifecycle.manager import AuthError
from evolver.proxy.sync.inbound import DEFAULT_POLL_INTERVAL_ACTIVE, DEFAULT_POLL_INTERVAL_IDLE, InboundSync
from evolver.proxy.sync.outbound import DEFAULT_OUTBOUND_INTERVAL, OutboundSync

logger = logging.getLogger(__name__)


class SyncEngine:
    def __init__(
        self,
        *,
        store: Any,
        hub_url: str | None = None,
        get_headers: Callable[[], dict[str, str]] | None = None,
        on_auth_error: Callable[[AuthError], None] | None = None,
    ) -> None:
        self._store = store
        self._outbound = OutboundSync(store=store, hub_url=hub_url, get_headers=get_headers)
        self._inbound = InboundSync(store=store, hub_url=hub_url, get_headers=get_headers)
        self._on_auth_error = on_auth_error

        self._running = False
        self._out_task: asyncio.Task[None] | None = None
        self._in_task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()
        self._out_notify = asyncio.Event()
        self._last_activity = time.time()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._shutdown_event.clear()
        self._out_notify.clear()
        self._out_task = asyncio.create_task(self._outbound_loop())
        self._in_task = asyncio.create_task(self._inbound_loop())
        logger.info("[SyncEngine] Started.")

    def stop(self) -> None:
        self._running = False
        self._shutdown_event.set()
        self._out_notify.set()
        if self._out_task is not None:
            self._out_task.cancel()
        if self._in_task is not None:
            self._in_task.cancel()
        logger.info("[SyncEngine] Stopped.")

    def notify_new_outbound(self) -> None:
        """Signal that new outbound messages are available — accelerate flush."""
        self._out_notify.set()
        self._last_activity = time.time()

    # ------------------------------------------------------------------
    # Outbound loop
    # ------------------------------------------------------------------

    async def _outbound_loop(self) -> None:
        while self._running and not self._shutdown_event.is_set():
            try:
                result = await self._outbound.flush()
                if result.get("sent", 0) > 0 or result.get("responses"):
                    self._last_activity = time.time()
            except AuthError as exc:
                if self._on_auth_error:
                    self._on_auth_error(exc)
            except Exception as exc:
                logger.warning("[SyncEngine] Outbound tick error: %s", exc)
            finally:
                # Schedule next tick
                if self._out_notify.is_set():
                    self._out_notify.clear()
                    delay = 0.1  # 100 ms accel
                elif self._store.count_pending(direction="outbound") > 0:
                    delay = 1.0
                else:
                    delay = DEFAULT_OUTBOUND_INTERVAL / 1000.0

                try:
                    await asyncio.wait_for(
                        asyncio.gather(
                            self._shutdown_event.wait(),
                            self._out_notify.wait(),
                            return_exceptions=True,
                        ),
                        timeout=delay,
                    )
                    self._out_notify.clear()
                except asyncio.TimeoutError:
                    pass

    # ------------------------------------------------------------------
    # Inbound loop
    # ------------------------------------------------------------------

    async def _inbound_loop(self) -> None:
        while self._running and not self._shutdown_event.is_set():
            try:
                result = await self._inbound.pull()
                if result.get("received", 0) > 0:
                    self._last_activity = time.time()
                # Opportunistically ACK delivered messages
                await self._inbound.ack_delivered()
            except AuthError as exc:
                if self._on_auth_error:
                    self._on_auth_error(exc)
            except Exception as exc:
                logger.warning("[SyncEngine] Inbound tick error: %s", exc)
            finally:
                idle_seconds = time.time() - self._last_activity
                if idle_seconds > 300:  # 5 minutes
                    delay = DEFAULT_POLL_INTERVAL_IDLE / 1000.0
                else:
                    delay = DEFAULT_POLL_INTERVAL_ACTIVE / 1000.0

                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=delay,
                    )
                except asyncio.TimeoutError:
                    pass
