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
from evolver.gep.node_identity import (
    is_valid_node_id,
    mint_node_id,
    persist_legacy_node_id,
    read_legacy_node_id,
    resolve_node_id,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HEARTBEAT_BACKOFF_CAP_MS = 15 * 60 * 1000
REAUTH_BACKOFF_BASE_MS = 5_000
REAUTH_BACKOFF_CAP_MS = 4 * 60 * 60 * 1000
WALL_CLOCK_DRIFT_THRESHOLD_S = 90
WALL_CLOCK_DRIFT_CLEAR_REAUTH_S = 30 * 60

# Hub-unreachable exponential backoff (Gap 3).  When the Hub is network-
# unreachable (DNS failure, connection refused, timeout — NOT auth errors),
# we back off exponentially to avoid hot-spinning.  Capped at 15 min.
HUB_UNREACHABLE_BACKOFF_BASE_MS = 5_000  # 5 s
HUB_UNREACHABLE_BACKOFF_CAP_MS = 15 * 60 * 1000  # 15 min

# Regex for a valid 64-hex node secret (matches the Hub's secret format).
_NODE_SECRET_RE = __import__("re").compile(r"^[a-f0-9]{64}$", __import__("re").IGNORECASE)

# L1: ERROR_BACKOFF — after 3 consecutive reauth failures, enter backoff (max 5 min).
ERROR_BACKOFF_THRESHOLD = 3
ERROR_BACKOFF_CAP_MS = 5 * 60 * 1000

# L5: Rate limiting — min interval between heartbeats (burst protection).
MIN_HEARTBEAT_INTERVAL_MS = 30_000  # 30s

# L4: Stale secret — a secret older than this (without refresh) is considered stale.
SECRET_STALE_TTL_S = 7 * 24 * 60 * 60  # 7 days


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
    # L1: ERROR_BACKOFF state
    in_error_backoff: bool = False
    error_backoff_until: float | None = None
    # L4: secret staleness tracking
    secret_set_at: float | None = None
    # L5: rate limiting
    last_heartbeat_attempt_at: float | None = None
    # L7: legacy node ID migration
    original_node_id: str | None = None
    # Gap 2: node secret versioning — Hub can rotate secrets and bump a
    # version.  When the store version < env version, the store secret is
    # stale (Hub rotated it) and must be cleared so hello re-registers.
    node_secret_version: int | None = None
    # Gap 3: hub-unreachable exponential backoff — network errors (not auth).
    hub_unreachable_failures: int = 0
    hub_unreachable_until: float | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_node_secret_version(value: Any) -> int | None:
    """Parse a node-secret version number from env or store.

    Returns the integer version, or ``None`` if missing/invalid.  Mirrors
    ``parseNodeSecretVersion`` in the Node.js lifecycle manager: only finite
    non-negative integers are accepted.
    """
    if value is None or value == "":
        return None
    try:
        n = int(value)
    except (ValueError, TypeError):
        return None
    return n if n >= 0 else None


def hub_unreachable_backoff_ms(failures: int) -> int:
    """Exponential backoff (ms) for *failures* consecutive Hub-unreachable errors.

    Capped at :data:`HUB_UNREACHABLE_BACKOFF_CAP_MS`.  Mirrors
    ``hubUnreachableBackoffMs`` in the Node.js lifecycle manager.
    """
    if failures <= 0:
        return 0
    backoff = HUB_UNREACHABLE_BACKOFF_BASE_MS * (2 ** (failures - 1))
    return int(min(backoff, HUB_UNREACHABLE_BACKOFF_CAP_MS))


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
        identity_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self._store = store
        self._version = version
        self._on_auth_error = on_auth_error
        self._on_force_update = on_force_update
        self._identity_provider = identity_provider
        self._delivery_identity_listeners: set[Callable[[], None]] = set()
        self._state = self._load_state()
        self._hub_url = resolve_hub_url()
        self._task: asyncio.Task[None] | None = None
        self._shutdown_event = asyncio.Event()
        self._poke_event = asyncio.Event()
        # H4: seed legacy ~/.evomap/node_id as soon as store id is known so
        # pre-hello force_update outcomes never land at force_update_last.anon.
        try:
            early = self._store.get_state("node_id") if self._store else None
            if is_valid_node_id(early):
                persist_legacy_node_id(str(early))
        except Exception as exc:
            logger.warning(
                "[Lifecycle] early persist of legacy node_id failed (non-fatal): %s",
                exc,
            )

    # ------------------------------------------------------------------
    # State persistence (via MailboxStore)
    # ------------------------------------------------------------------

    def _load_state(self) -> LifecycleState:
        s = LifecycleState()
        # Node secret resolution (Gap 2: versioned secrets).
        env_secret = os.environ.get("A2A_NODE_SECRET", "").strip()
        store_secret = self._store.get_state("node_secret")
        store_source = self._store.get_state("node_secret_source") or "env_seed"
        store_id = self._store.get_state("node_id")

        # Gap 2: resolve node_secret_version from store and env.  When the
        # store version is OLDER than the env version, the Hub has rotated
        # the secret out from under us — the store secret is stale and must
        # be discarded so hello re-registers with the env secret.
        env_version = parse_node_secret_version(
            os.environ.get("A2A_NODE_SECRET_VERSION")
            or os.environ.get("EVOMAP_NODE_SECRET_VERSION")
        )
        store_version = parse_node_secret_version(self._store.get_state("node_secret_version"))
        s.node_secret_version = store_version if store_version is not None else env_version

        store_secret_valid = isinstance(store_secret, str) and bool(
            _NODE_SECRET_RE.match(store_secret)
        )
        if (
            store_secret_valid
            and env_version is not None
            and store_version is not None
            and store_version < env_version
        ):
            # Hub rotated: store secret is stale, clear it.
            logger.info(
                "[Lifecycle] Store node_secret (v%d) is older than env (v%d); "
                "clearing stale store secret",
                store_version,
                env_version,
            )
            store_secret = None
            store_secret_valid = False

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

        # Identity precedence: store > env > legacy file (no mint on load).
        resolved = resolve_node_id(store_id=store_id, allow_mint=False)
        if resolved is None and store_id:
            # Keep non-canonical store values (pre-migration legacy prefixes).
            resolved = str(store_id).strip() or None
        s.node_id = resolved
        s.last_heartbeat_at = self._store.get_state("last_heartbeat_at")
        # L4: load secret age
        s.secret_set_at = self._store.get_state("secret_set_at")
        # L7: load original node ID for legacy fallback
        s.original_node_id = self._store.get_state("original_node_id")
        # Migrate legacy node ID if needed.
        if s.node_id:
            for prefix in self._LEGACY_NODE_ID_PREFIXES:
                if s.node_id.startswith(prefix):
                    s.original_node_id = s.node_id
                    s.node_id = s.node_id[len(prefix) :]
                    break
        return s

    def _save_state(self) -> None:
        self._store.set_state("node_id", self._state.node_id)
        self._store.set_state("node_secret", self._state.node_secret)
        self._store.set_state("node_secret_source", self._state.node_secret_source)
        self._store.set_state("node_secret_version", self._state.node_secret_version)
        self._store.set_state("last_heartbeat_at", self._state.last_heartbeat_at)
        self._store.set_state("secret_set_at", self._state.secret_set_at)
        self._store.set_state("original_node_id", self._state.original_node_id)

    # ------------------------------------------------------------------
    # Identity surface (v1.92.0 nodeId unification)
    # ------------------------------------------------------------------

    @property
    def node_id(self) -> str | None:
        """Active node id (store-backed; mirrors Node ``nodeId`` getter)."""
        if self._identity_provider is not None:
            try:
                provided = self._identity_provider()
                if provided:
                    return str(provided)
            except Exception:
                pass
        store_id = self._store.get_state("node_id") if self._store else None
        if store_id:
            return str(store_id)
        return self._state.node_id

    # CamelCase alias for Node-facing parity in tests / integrations.
    @property
    def nodeId(self) -> str | None:  # noqa: N802
        return self.node_id

    def on_delivery_identity_change(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register a listener fired when delivery identity (node/secret) changes.

        Returns an unsubscribe callable.
        """
        if not callable(listener):
            return lambda: None
        self._delivery_identity_listeners.add(listener)

        def _unsubscribe() -> None:
            self._delivery_identity_listeners.discard(listener)

        return _unsubscribe

    # CamelCase alias.
    def onDeliveryIdentityChange(  # noqa: N802
        self, listener: Callable[[], None]
    ) -> Callable[[], None]:
        return self.on_delivery_identity_change(listener)

    def _notify_delivery_identity_change(self) -> None:
        for listener in list(self._delivery_identity_listeners):
            try:
                listener()
            except Exception:
                logger.warning("[Lifecycle] delivery identity listener failed")

    # ------------------------------------------------------------------
    # Gap 2: Node secret versioning
    # ------------------------------------------------------------------

    @property
    def node_secret_version(self) -> int | None:
        """Resolve the effective node-secret version (store > env).

        Mirrors ``nodeSecretVersion`` in the Node.js lifecycle manager: the
        store version takes precedence (it's what the Hub last gave us), and
        falls back to the env version.
        """
        store_version = parse_node_secret_version(self._store.get_state("node_secret_version"))
        if store_version is not None:
            return store_version
        return parse_node_secret_version(
            os.environ.get("A2A_NODE_SECRET_VERSION")
            or os.environ.get("EVOMAP_NODE_SECRET_VERSION")
        )

    # ------------------------------------------------------------------
    # Gap 3: Hub-unreachable exponential backoff
    # ------------------------------------------------------------------

    def _record_hub_unreachable(self, err: BaseException | None = None) -> int:
        """Record a Hub-unreachable failure and return the backoff wait (ms).

        Call this on network errors (NOT auth errors) to back off
        exponentially.  Returns the ms to wait before the next attempt.
        """
        self._state.hub_unreachable_failures += 1
        wait_ms = hub_unreachable_backoff_ms(self._state.hub_unreachable_failures)
        self._state.hub_unreachable_until = time.time() + wait_ms / 1000.0
        logger.warning(
            "[Lifecycle] Hub unreachable (failure #%d): %s; backing off %.0f ms",
            self._state.hub_unreachable_failures,
            err,
            wait_ms,
        )
        return wait_ms

    def _record_hub_reachable(self) -> None:
        """Reset the Hub-unreachable backoff after a successful request."""
        if self._state.hub_unreachable_failures > 0:
            logger.info(
                "[Lifecycle] Hub reachable again after %d failures",
                self._state.hub_unreachable_failures,
            )
        self._state.hub_unreachable_failures = 0
        self._state.hub_unreachable_until = None

    def _hub_unreachable_wait_ms(self) -> int:
        """Return ms remaining in the Hub-unreachable backoff, or 0 if clear."""
        if self._state.hub_unreachable_until is None:
            return 0
        remaining = (self._state.hub_unreachable_until - time.time()) * 1000
        if remaining <= 0:
            self._state.hub_unreachable_until = None
            return 0
        return int(remaining)

    # ------------------------------------------------------------------
    # Hello
    # ------------------------------------------------------------------

    async def hello(  # noqa: PLR0912, PLR0915
        self, *, rotate_secret: bool = False
    ) -> dict[str, Any]:
        """Register or re-register with the Hub."""
        # Gap 3: respect Hub-unreachable backoff.
        wait_ms = self._hub_unreachable_wait_ms()
        if wait_ms > 0:
            return {"ok": False, "error": "hub_unreachable_backoff", "wait_ms": wait_ms}

        # Resolve identity before the wire call:
        # store (already loaded) → env → legacy file → mint.
        previous_id = self._state.node_id
        if not self._state.node_id:
            legacy = read_legacy_node_id()
            if legacy:
                self._state.node_id = legacy
            else:
                env_id = (os.environ.get("A2A_NODE_ID") or "").strip()
                if env_id:
                    self._state.node_id = env_id
                else:
                    self._state.node_id = mint_node_id()

        payload: dict[str, Any] = {
            "protocol": "gep-a2a",
            "protocol_version": "1.0.0",
            "message_type": "hello",
            "env_fingerprint": capture_env_fingerprint(),
            "sender_id": self._state.node_id,
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
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            # Gap 3: network-unreachable — back off.
            self._record_hub_unreachable(exc)
            return {"ok": False, "error": "hub_unreachable", "detail": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        # Gap 3: Hub is reachable — reset backoff.
        self._record_hub_reachable()

        # Prefer nested payload fields when Hub wraps the ack.
        payload_body = body.get("payload") if isinstance(body.get("payload"), dict) else {}
        hub_node_id = body.get("node_id") or payload_body.get("node_id")
        hub_secret = body.get("node_secret") or payload_body.get("node_secret")

        if hub_node_id:
            self._state.node_id = str(hub_node_id)
        if hub_secret:
            self._state.node_secret = str(hub_secret)
            self._state.node_secret_source = "hub_rotate"
        # Gap 2: persist the secret version the Hub returned (if any).
        hub_version = parse_node_secret_version(
            body.get("node_secret_version") or payload_body.get("node_secret_version")
        )
        if hub_version is not None:
            self._state.node_secret_version = hub_version
        self._save_state()

        # Unify legacy ~/.evomap/node_id with the id sent on the wire.
        try:
            if self._state.node_id:
                persist_legacy_node_id(self._state.node_id)
        except Exception as exc:
            logger.warning(
                "[Lifecycle] post-hello legacy node_id persist failed (non-fatal): %s",
                exc,
            )

        if previous_id != self._state.node_id or hub_secret:
            self._notify_delivery_identity_change()

        return {
            "ok": True,
            "node_id": self._state.node_id,
            "nodeId": self._state.node_id,
            "hub_response": body,
        }

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def heartbeat(self, *, _skip_reauth: bool = False) -> dict[str, Any]:  # noqa: PLR0911, PLR0912, PLR0915
        """Send a heartbeat to the Hub."""
        # L1: Skip if in ERROR_BACKOFF.
        if self._is_in_error_backoff():
            return {"ok": False, "error": "error_backoff"}

        # L5: Rate limit check.
        if not _skip_reauth and not self._check_rate_limit():
            return {"ok": False, "error": "rate_limited"}

        # Gap 3: respect Hub-unreachable backoff.
        wait_ms = self._hub_unreachable_wait_ms()
        if wait_ms > 0:
            return {"ok": False, "error": "hub_unreachable_backoff", "wait_ms": wait_ms}

        self._state.last_heartbeat_attempt_at = time.time()

        if not self._state.node_id:
            return {"ok": False, "error": "no_node_id"}

        meta = {
            "proxy_version": self._version,
            "outbound_pending": self._store.count_pending(direction="outbound"),
            "inbound_pending": self._store.count_pending(direction="inbound"),
        }

        # Gap 4: anti-abuse telemetry envelope (privacy-preserving heartbeat summary).
        from evolver.config import anti_abuse_telemetry_mode

        if anti_abuse_telemetry_mode() == "heartbeat":
            from evolver.gep.anti_abuse_telemetry import build_heartbeat_anti_abuse

            meta["anti_abuse"] = build_heartbeat_anti_abuse(
                env_fingerprint=capture_env_fingerprint(),
                node_id=self._state.node_id,
                task_metrics=self._store.get_state("task_metrics"),
            )

        payload: dict[str, Any] = {
            "node_id": self._state.node_id,
            "evolver_version": self._version,
            "env_fingerprint": capture_env_fingerprint(),
            "meta": meta,
        }

        # Gap 7: carry the pending last-update ack so the Hub can confirm.
        pending_ack = self._read_pending_last_update()
        if pending_ack:
            payload["last_update_ack"] = pending_ack

        # Gap 2: carry our current secret version so the Hub knows what we have.
        if self._state.node_secret_version is not None:
            payload["node_secret_version"] = self._state.node_secret_version

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
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            # Gap 3: network-unreachable — back off.
            self._record_hub_unreachable(exc)
            return {"ok": False, "error": "hub_unreachable", "detail": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        # Gap 3: Hub is reachable — reset backoff.
        self._record_hub_reachable()

        # Success
        self._state.last_heartbeat_at = int(time.time() * 1000)
        self._state.heartbeat_failures = 0
        # Gap 2: persist secret version if the Hub rotated.
        hub_version = parse_node_secret_version(
            body.get("node_secret_version") or body.get("payload", {}).get("node_secret_version")
        )
        if hub_version is not None and hub_version != self._state.node_secret_version:
            self._state.node_secret_version = hub_version
            if body.get("node_secret"):
                self._state.node_secret = body["node_secret"]
                self._state.node_secret_source = "hub_rotate"
        self._save_state()

        # Gap 6: Force-update from heartbeat — with retry cooldown so the Hub
        # cannot hot-spin force-updates on every heartbeat.
        fu = body.get("force_update")
        if fu and self._on_force_update:
            self._maybe_trigger_force_update_from_heartbeat(fu)

        # Gap 7: Last-update ack — carry the pending last-update id so the Hub
        # can confirm our previous update was received.
        last_update_ack = self._read_pending_last_update()
        if last_update_ack:
            # We've acknowledged it locally; the heartbeat body already carried
            # it (set in the payload builder). Clear the pending flag.
            self._store.set_state("pending_last_update_ack", None)

        from evolver.atp.heartbeat_signals_handler import handle_signals

        atp_summary = await handle_signals(body)
        return {"ok": True, "hub_response": body, "atp_signals": atp_summary}

    def _get_force_update_retry_cooldown_ms(self) -> int:
        """Return the force-update retry cooldown (ms).

        Prevents the Hub from re-triggering force-updates on every heartbeat.
        Configurable via ``EVOLVER_FORCE_UPDATE_RETRY_COOLDOWN_MS`` (default 5 min).
        """
        raw = os.environ.get("EVOLVER_FORCE_UPDATE_RETRY_COOLDOWN_MS")
        if raw:
            try:
                n = int(raw)
                if n > 0:
                    return n
            except ValueError:
                pass
        return 5 * 60 * 1000  # 5 min default

    def _maybe_trigger_force_update_from_heartbeat(self, directive: dict[str, Any]) -> bool:
        """Trigger a force-update from a heartbeat response, respecting cooldown.

        Returns True if triggered, False if skipped (in-flight or on cooldown).
        Mirrors ``_maybeTriggerForceUpdateFromHeartbeat`` in the Node.js manager.
        """
        if self._state.force_update_in_flight:
            logger.debug("[Lifecycle] Force-update already in-flight; skipping")
            return False

        now = time.time()
        cooldown_s = self._get_force_update_retry_cooldown_ms() / 1000.0
        if (
            self._state.force_update_last_attempt_at
            and (now - self._state.force_update_last_attempt_at) < cooldown_s
        ):
            logger.debug(
                "[Lifecycle] Force-update on cooldown (%.0f s remaining)",
                cooldown_s - (now - self._state.force_update_last_attempt_at),
            )
            return False

        self._state.force_update_in_flight = True
        self._state.force_update_last_attempt_at = now
        asyncio.create_task(self._run_force_update(directive))
        return True

    def _read_pending_last_update(self) -> str | None:
        """Read the pending last-update acknowledgment id.

        Mirrors ``readPendingLastUpdate`` in the Node.js manager.  Returns the
        id of the last update we haven't yet acknowledged to the Hub, or None.
        """
        val = self._store.get_state("pending_last_update_ack")
        return str(val) if val else None

    def set_pending_last_update(self, update_id: str) -> None:
        """Record a pending last-update acknowledgment."""
        self._store.set_state("pending_last_update_ack", update_id)

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
        self._enter_error_backoff()  # L1: may enter ERROR_BACKOFF
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
    # L1: ERROR_BACKOFF — enter/exit backoff state after repeated reauth failures
    # ------------------------------------------------------------------

    def _enter_error_backoff(self) -> None:
        """Enter ERROR_BACKOFF state after ERROR_BACKOFF_THRESHOLD reauth failures."""
        if self._state.reauth_failures >= ERROR_BACKOFF_THRESHOLD:
            self._state.in_error_backoff = True
            backoff = min(
                ERROR_BACKOFF_CAP_MS,
                REAUTH_BACKOFF_BASE_MS * (2 ** (self._state.reauth_failures - 1)),
            )
            self._state.error_backoff_until = time.time() + backoff / 1000.0
            logger.warning(
                "[Lifecycle] Entering ERROR_BACKOFF for %.0f s (reauth_failures=%d)",
                backoff / 1000.0,
                self._state.reauth_failures,
            )

    def _is_in_error_backoff(self) -> bool:
        """Return True if currently in ERROR_BACKOFF and the timeout hasn't elapsed."""
        if not self._state.in_error_backoff:
            return False
        if self._state.error_backoff_until and time.time() < self._state.error_backoff_until:
            return True
        # Backoff period elapsed — exit.
        self._state.in_error_backoff = False
        self._state.error_backoff_until = None
        return False

    # ------------------------------------------------------------------
    # L2: TLS enforcement
    # ------------------------------------------------------------------

    @staticmethod
    def enforce_tls(url: str | None = None) -> dict[str, Any]:
        """Validate that the Hub URL uses HTTPS.

        Returns ``{ok: bool, url: str, warnings: list[str]}``.
        In production (``EVOLVER_ENV=production``), non-HTTPS URLs are rejected.
        In development, a warning is issued but the URL is accepted.
        """
        hub_url = url or resolve_hub_url()
        warnings: list[str] = []
        is_production = os.environ.get("EVOLVER_ENV", "").lower() == "production"

        if not hub_url:
            return {"ok": False, "url": "", "warnings": ["hub_url_empty"]}

        if hub_url.startswith("https://"):
            return {"ok": True, "url": hub_url, "warnings": []}

        if hub_url.startswith("http://"):
            msg = f"Hub URL is not HTTPS: {hub_url}"
            if is_production:
                return {
                    "ok": False,
                    "url": hub_url,
                    "warnings": [msg, "tls_rejected_in_production"],
                }
            warnings.append(msg)
            warnings.append("tls_warning_dev_only")
            return {"ok": True, "url": hub_url, "warnings": warnings}

        # No protocol — assume HTTPS is needed.
        warnings.append(f"Hub URL has no protocol: {hub_url}")
        return {"ok": True, "url": hub_url, "warnings": warnings}

    # ------------------------------------------------------------------
    # L3: Offline permit — atomic flag for hub-verify offline mode
    # ------------------------------------------------------------------

    def acquire_offline_permit(self) -> bool:
        """Atomically acquire an offline permit for hub-verify.

        Returns True if acquired (or already held), False if contended.
        The permit prevents two concurrent verify-while-offline races.
        """
        current = self._store.get_state("offline_permit_holder")
        if current == self._state.node_id:
            return True  # already held
        if current:
            return False  # held by another node
        self._store.set_state("offline_permit_holder", self._state.node_id)
        # Re-read to confirm we won the race.
        holder = self._store.get_state("offline_permit_holder")
        return bool(holder == self._state.node_id)

    def release_offline_permit(self) -> None:
        """Release the offline permit (only if we hold it)."""
        current = self._store.get_state("offline_permit_holder")
        if current == self._state.node_id:
            self._store.set_state("offline_permit_holder", None)

    # ------------------------------------------------------------------
    # L4: Stale node secret detection and rotation
    # ------------------------------------------------------------------

    def is_secret_stale(self) -> bool:
        """Return True if the node secret hasn't been refreshed in SECRET_STALE_TTL_S."""
        if not self._state.secret_set_at:
            return True  # never set → stale
        return time.time() - self._state.secret_set_at > SECRET_STALE_TTL_S

    async def rotate_stale_secret(self) -> dict[str, Any]:
        """Rotate the node secret if it's stale.

        Calls ``hello(rotate_secret=True)`` to get a fresh secret from the Hub.
        """
        if not self.is_secret_stale():
            return {"ok": True, "rotated": False, "reason": "not_stale"}
        logger.info("[Lifecycle] Node secret is stale, rotating...")
        result = await self.hello(rotate_secret=True)
        if result.get("ok"):
            self._state.secret_set_at = time.time()
            self._save_state()
            return {"ok": True, "rotated": True}
        return result

    # ------------------------------------------------------------------
    # L5: Rate limiting
    # ------------------------------------------------------------------

    def _check_rate_limit(self) -> bool:
        """Return True if enough time has passed since the last heartbeat attempt.

        Prevents burst-sending heartbeats when the loop is poked repeatedly.
        """
        if self._state.last_heartbeat_attempt_at is None:
            return True
        elapsed_ms = (time.time() - self._state.last_heartbeat_attempt_at) * 1000
        return bool(elapsed_ms >= MIN_HEARTBEAT_INTERVAL_MS)

    # ------------------------------------------------------------------
    # L7: Node ID legacy fallback
    # ------------------------------------------------------------------

    _LEGACY_NODE_ID_PREFIXES = ("evomap-", "node-", "a2a-")

    def resolve_legacy_node_id(self) -> str | None:
        """Detect and migrate a legacy-format node ID.

        Legacy IDs used prefixes like ``evomap-`` or ``node-``. This method
        strips the prefix and stores the original for backward compatibility.
        If the current node_id has no legacy prefix, returns it unchanged.
        """
        nid = self._state.node_id
        if not nid:
            return None
        for prefix in self._LEGACY_NODE_ID_PREFIXES:
            if nid.startswith(prefix):
                # Store original for backward-compat lookups.
                if not self._state.original_node_id:
                    self._state.original_node_id = nid
                migrated = nid[len(prefix) :]
                logger.info(
                    "[Lifecycle] Migrating legacy node ID: %s -> %s",
                    nid,
                    migrated,
                )
                self._state.node_id = migrated
                self._save_state()
                return migrated
        return nid

    def get_effective_node_id(self) -> str | None:
        """Return the node ID, checking legacy fallback if needed."""
        nid = self._state.node_id
        if nid:
            return nid
        # Fallback to original (legacy) if current is somehow cleared.
        return self._state.original_node_id

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
