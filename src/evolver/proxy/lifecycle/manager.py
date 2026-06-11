"""Proxy lifecycle manager — hello, heartbeat, re-auth, force-update.

Equivalent to ``evolver/src/proxy/lifecycle/manager.js``.
Manages the full lifecycle of a proxy node talking to the EvoMap Hub:
registration (hello), continuous heartbeats, automatic recovery from 401/403,
and forced-update orchestration.

Design notes (Pythonic)
-----------------------
* Async-first: all network calls are ``async`` using ``httpx``.
* State is persisted through the ``MailboxStore`` (node_id, node_secret,
  last_heartbeat_at, etc.) so the proxy survives restarts.
* Heartbeat loop is a cancellable ``asyncio.Task`` with graceful shutdown.
* Clock-jump detection uses ``time.monotonic()`` vs ``time.time()`` to detect
  system sleep / resume (especially macOS) and immediately poke a heartbeat.
* Exponential backoff for heartbeat failures is capped at 15 min.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from evolver.config import (
    HEARTBEAT_FIRST_DELAY_MS,
    HEARTBEAT_INTERVAL_MS,
    HELLO_TIMEOUT_MS,
    HTTP_TRANSPORT_TIMEOUT_MS,
    resolve_hub_url,
)
from evolver.gep.env_fingerprint import capture_env_fingerprint

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HEARTBEAT_BACKOFF_CAP_MS = 15 * 60 * 1000
REAUTH_BACKOFF_BASE_MS = 5_000
REAUTH_BACKOFF_CAP_MS = 4 * 60 * 60 * 1000
WALL_CLOCK_DRIFT_THRESHOLD_S = 90
WALL_CLOCK_DRIFT_CLEAR_REAUTH_S = 30 * 60


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class LifecycleState:
    node_id: str | None = None
    node_secret: str | None = None
    node_secret_source: str = "env_seed"  # env_seed | hub_rotate
    last_heartbeat_at: int | None = None
    heartbeat_failures: int = 0
    reauth_failures: int = 0
    last_reauth_at: float | None = None
    force_update_in_flight: bool = False
    force_update_last_attempt_at: float | None = None


# ---------------------------------------------------------------------------
# LifecycleManager
# ---------------------------------------------------------------------------


class LifecycleManager:
    def __init__(
        self,
        *,
        store: Any,
        version: str = "1.0.0",
        on_auth_error: Callable[[AuthError], None] | None = None,
        on_force_update: Callable[[], None] | None = None,
    ) -> None:
        self._store = store
        self._version = version
        self._on_auth_error = on_auth_error
        self._on_force_update = on_force_update
        self._state = self._load_state()
        self._hub_url = resolve_hub_url()
        self._task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()
        self._poke_event = asyncio.Event()

    # ------------------------------------------------------------------
    # State persistence (via MailboxStore)
    # ------------------------------------------------------------------

    def _load_state(self) -> LifecycleState:
        s = LifecycleState()
        # Node secret resolution
        env_secret = os.environ.get("A2A_NODE_SECRET", "").strip()
        store_secret = self._store.get_state("node_secret")
        store_source = self._store.get_state("node_secret_source") or "env_seed"
        store_id = self._store.get_state("node_id")

        if store_secret and env_secret and store_secret != env_secret:
            # Conflict arbitration
            if store_source == "hub_rotate":
                s.node_secret = store_secret
                s.node_secret_source = "hub_rotate"
            else:
                s.node_secret = env_secret
                s.node_secret_source = "env_seed"
        elif store_secret:
            s.node_secret = store_secret
            s.node_secret_source = store_source
        elif env_secret:
            s.node_secret = env_secret
            s.node_secret_source = "env_seed"

        s.node_id = store_id or os.environ.get("A2A_NODE_ID", "").strip() or None
        s.last_heartbeat_at = self._store.get_state("last_heartbeat_at")
        return s

    def _save_state(self) -> None:
        self._store.set_state("node_id", self._state.node_id)
        self._store.set_state("node_secret", self._state.node_secret)
        self._store.set_state("node_secret_source", self._state.node_secret_source)
        self._store.set_state("last_heartbeat_at", self._state.last_heartbeat_at)

    # ------------------------------------------------------------------
    # Hello
    # ------------------------------------------------------------------

    async def hello(self, *, rotate_secret: bool = False) -> dict[str, Any]:
        """Register or re-register with the Hub."""
        payload: dict[str, Any] = {
            "protocol": "gep-a2a",
            "protocol_version": "1.0.0",
            "message_type": "hello",
            "env_fingerprint": capture_env_fingerprint(),
        }
        if self._state.node_id:
            payload["node_id"] = self._state.node_id
        if rotate_secret and self._state.node_secret:
            payload["rotate_secret"] = True

        headers = {"Content-Type": "application/json"}
        if self._state.node_secret:
            headers["Authorization"] = f"Bearer {self._state.node_secret}"

        try:
            async with httpx.AsyncClient(http2=True, timeout=HELLO_TIMEOUT_MS / 1000.0) as client:
                response = await client.post(
                    f"{self._hub_url}/v1/a2a/hello",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise AuthError(str(exc), exc.response.status_code)
            return {"ok": False, "error": str(exc), "status_code": exc.response.status_code}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        # Update local state from response
        if body.get("node_id"):
            self._state.node_id = body["node_id"]
        if body.get("node_secret"):
            self._state.node_secret = body["node_secret"]
            self._state.node_secret_source = "hub_rotate"
        self._save_state()
        return {"ok": True, "hub_response": body}

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def heartbeat(self, *, _skip_reauth: bool = False) -> dict[str, Any]:
        """Send a heartbeat to the Hub."""
        if not self._state.node_id:
            return {"ok": False, "error": "no_node_id"}

        meta = {
            "proxy_version": self._version,
            "outbound_pending": self._store.count_pending(direction="outbound"),
            "inbound_pending": self._store.count_pending(direction="inbound"),
        }

        payload: dict[str, Any] = {
            "node_id": self._state.node_id,
            "evolver_version": self._version,
            "env_fingerprint": capture_env_fingerprint(),
            "meta": meta,
        }

        headers = {"Content-Type": "application/json"}
        if self._state.node_secret:
            headers["Authorization"] = f"Bearer {self._state.node_secret}"

        try:
            async with httpx.AsyncClient(
                http2=True, timeout=HTTP_TRANSPORT_TIMEOUT_MS / 1000.0
            ) as client:
                response = await client.post(
                    f"{self._hub_url}/v1/a2a/heartbeat",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403) and not _skip_reauth:
                if self._on_auth_error:
                    self._on_auth_error(AuthError(str(exc), exc.response.status_code))
                return {"ok": False, "error": "auth_error", "status_code": exc.response.status_code}
            return {"ok": False, "error": str(exc), "status_code": exc.response.status_code}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        # Success
        self._state.last_heartbeat_at = int(time.time() * 1000)
        self._state.heartbeat_failures = 0
        self._save_state()

        # Check for force_update directive
        if body.get("force_update") and self._on_force_update:
            if not self._state.force_update_in_flight:
                self._state.force_update_in_flight = True
                self._state.force_update_last_attempt_at = time.time()
                asyncio.create_task(self._run_force_update(body["force_update"]))

        from evolver.atp.heartbeat_signals_handler import handle_signals

        atp_summary = await handle_signals(body)
        return {"ok": True, "hub_response": body, "atp_signals": atp_summary}

    async def _run_force_update(self, directive: dict[str, Any]) -> None:
        """Execute a forced update in the background."""
        try:
            logger.warning("[Lifecycle] Force update triggered: %s", directive)
            if self._on_force_update:
                self._on_force_update()
        finally:
            self._state.force_update_in_flight = False

    # ------------------------------------------------------------------
    # Re-authentication
    # ------------------------------------------------------------------

    async def re_authenticate(self) -> dict[str, Any]:
        """Recover from 401/403 by re-authenticating with the Hub."""
        now = time.time()
        if self._state.last_reauth_at:
            backoff = min(
                REAUTH_BACKOFF_CAP_MS,
                REAUTH_BACKOFF_BASE_MS * (2 ** max(0, self._state.reauth_failures - 1)),
            )
            if (now - self._state.last_reauth_at) * 1000 < backoff:
                return {"ok": False, "error": "backoff"}

        self._state.last_reauth_at = now

        # Attempt 1: rotate secret
        try:
            result = await self.hello(rotate_secret=True)
            if result.get("ok"):
                self._state.reauth_failures = 0
                return result
        except AuthError:
            pass

        # Attempt 2: clear secret and try lenient hello
        old_secret = self._state.node_secret
        self._state.node_secret = None
        try:
            result = await self.hello()
            if result.get("ok"):
                self._state.reauth_failures = 0
                return result
        except AuthError:
            pass

        # Restore old secret for next attempt
        self._state.node_secret = old_secret
        self._state.reauth_failures += 1
        self._save_state()
        return {"ok": False, "error": "reauth_failed"}

    # ------------------------------------------------------------------
    # Heartbeat loop
    # ------------------------------------------------------------------

    def start_heartbeat_loop(self, interval_ms: int = HEARTBEAT_INTERVAL_MS) -> None:
        if self._task is not None and not self._task.done():
            return
        self._shutdown_event.clear()
        self._poke_event.clear()
        self._task = asyncio.create_task(self._heartbeat_loop(interval_ms))
        logger.info("[Lifecycle] Heartbeat loop started (interval=%d ms)", interval_ms)

    def stop_heartbeat_loop(self) -> None:
        self._shutdown_event.set()
        self._poke_event.set()  # wake the loop
        if self._task is not None:
            self._task.cancel()

    def poke_heartbeat_loop(self) -> None:
        self._poke_event.set()

    @property
    def connection_status(self) -> str:
        if not self._state.node_id:
            return "unregistered"
        if self._state.last_heartbeat_at:
            age_ms = int(time.time() * 1000) - int(self._state.last_heartbeat_at)
            if age_ms < HEARTBEAT_INTERVAL_MS * 3:
                return "connected"
        return "idle"

    @property
    def state(self) -> str:
        """String status for proxy routes (Node.js compatibility)."""
        status = self.connection_status
        if status == "connected":
            return "HEARTBEATING"
        if self._state.node_id:
            return "AUTHENTICATED"
        return "IDLE"

    async def _heartbeat_loop(self, interval_ms: int) -> None:
        # Initial delay (responds to poke as well)
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    self._shutdown_event.wait(),
                    self._poke_event.wait(),
                    return_exceptions=True,
                ),
                timeout=HEARTBEAT_FIRST_DELAY_MS / 1000.0,
            )
            self._poke_event.clear()
            if self._shutdown_event.is_set():
                return
        except TimeoutError:
            pass

        prev_wall = time.time()
        prev_mono = time.monotonic()

        while not self._shutdown_event.is_set():
            now_wall = time.time()
            now_mono = time.monotonic()
            wall_delta = now_wall - prev_wall
            mono_delta = now_mono - prev_mono
            drift = wall_delta - mono_delta

            if drift > WALL_CLOCK_DRIFT_THRESHOLD_S:
                logger.info(
                    "[Lifecycle] Wall-clock jump detected (+%.0f s), poking heartbeat",
                    drift,
                )
                if drift > WALL_CLOCK_DRIFT_CLEAR_REAUTH_S:
                    self._state.reauth_failures = 0

            result: dict[str, Any] = {"ok": False}
            try:
                result = await self.heartbeat()
                if not result.get("ok"):
                    self._state.heartbeat_failures += 1
                    logger.warning("[Lifecycle] Heartbeat failed: %s", result.get("error"))
            except Exception as exc:
                self._state.heartbeat_failures += 1
                logger.warning("[Lifecycle] Heartbeat exception: %s", exc)

            prev_wall = time.time()
            prev_mono = time.monotonic()

            # Compute backoff interval
            backoff = min(
                HEARTBEAT_BACKOFF_CAP_MS,
                interval_ms * (2**self._state.heartbeat_failures),
            )
            if result.get("ok"):
                actual_interval = interval_ms / 1000.0
            else:
                actual_interval = backoff / 1000.0

            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        self._shutdown_event.wait(),
                        self._poke_event.wait(),
                        return_exceptions=True,
                    ),
                    timeout=actual_interval,
                )
                self._poke_event.clear()
            except TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Version comparison
    # ------------------------------------------------------------------

    @staticmethod
    def should_upgrade(current: str, min_version: str) -> bool:
        """Return True if *min_version* is newer than *current*."""
        try:
            from packaging.version import Version as V

            return V(min_version) > V(current)
        except Exception:
            # Fallback: simple tuple comparison
            def _parse(v: str) -> tuple[int, ...]:
                return tuple(int(x) for x in v.split(".") if x.isdigit())

            return _parse(min_version) > _parse(current)
