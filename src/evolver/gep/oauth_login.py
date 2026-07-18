"""OAuth login flow — authenticate with external services via OAuth 2.0.

Equivalent to ``evolver/src/gep/oauthLogin.js`` (165 lines).

Provides a device-code OAuth flow for services that require user
authentication (e.g. Google Drive, GitHub Apps). The flow:
  1. Request a device code from the provider.
  2. Display the verification URL + user code.
  3. Poll the token endpoint until the user authorizes.
  4. Store the access/refresh tokens via ``workspace_keychain``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

from evolver.gep.workspace_keychain import WorkspaceKeychain

_keychain: WorkspaceKeychain | None = None


def _get_keychain() -> WorkspaceKeychain:
    global _keychain  # noqa: PLW0603
    if _keychain is None:
        _keychain = WorkspaceKeychain()
    return _keychain


logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 5
_POLL_TIMEOUT_S = 300


async def start_device_flow(
    provider: str,
    client_id: str,
    device_code_url: str,
    scopes: list[str] | None = None,
) -> dict[str, Any]:
    """Initiate a device-code OAuth flow.

    Returns the device code response (contains ``user_code``,
    ``verification_uri``, ``device_code``, ``expires_in``, ``interval``).
    """
    payload: dict[str, Any] = {"client_id": client_id}
    if scopes:
        payload["scope"] = " ".join(scopes)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(device_code_url, data=payload)
            resp.raise_for_status()
            data = resp.json()
            data["provider"] = provider
            return {"ok": True, "data": data}
    except Exception as exc:
        logger.warning("[oauth] device flow start failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def poll_for_token(
    token_url: str,
    client_id: str,
    device_code: str,
    interval: int = 5,
    expires_in: int = 300,
) -> dict[str, Any]:
    """Poll the token endpoint until the user authorizes or timeout.

    Returns ``{ok: True, access_token, refresh_token}`` on success,
    or ``{ok: False, error}`` on timeout/denial.
    """
    deadline = time.time() + min(expires_in, _POLL_TIMEOUT_S)
    poll_interval = max(interval, _POLL_INTERVAL_S)

    while time.time() < deadline:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    token_url,
                    data={
                        "client_id": client_id,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                )
                data = resp.json()
                if resp.status_code == 200:
                    return {
                        "ok": True,
                        "access_token": data.get("access_token", ""),
                        "refresh_token": data.get("refresh_token", ""),
                        "expires_in": data.get("expires_in", 3600),
                    }
                error = data.get("error", "")
                if error == "authorization_pending":
                    await _sleep(poll_interval)
                    continue
                if error == "slow_down":
                    poll_interval += 5
                    continue
                if error in ("expired_token", "access_denied"):
                    return {"ok": False, "error": error}
        except Exception as exc:
            logger.debug("[oauth] poll error: %s", exc)
            await _sleep(poll_interval)

    return {"ok": False, "error": "timeout"}


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def store_tokens(provider: str, access_token: str, refresh_token: str = "") -> None:
    """Store OAuth tokens in the workspace keychain."""
    kc = _get_keychain()
    kc.set(f"oauth:{provider}:access_token", access_token)
    if refresh_token:
        kc.set(f"oauth:{provider}:refresh_token", refresh_token)


def get_access_token(provider: str) -> str | None:
    """Retrieve a stored access token."""
    val = _get_keychain().get(f"oauth:{provider}:access_token")
    return str(val) if val else None


def load_valid_oauth_access_token(
    *,
    path: Path | None = None,
    now_ms: int | None = None,
) -> str | None:
    """Load a non-expired OAuth access token from ``~/.evomap/oauth_token.json``.

    Used by ``sync --dry-run`` OAuth-only auth (syncOAuthDryRun). Returns
    ``None`` when missing, unreadable, or past ``expires_at``.
    """
    from evolver.gep.paths import get_evolver_home  # noqa: PLC0415

    token_path = path or (get_evolver_home() / "oauth_token.json")
    try:
        if not token_path.is_file():
            return None
        data = json.loads(token_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(data, dict):
        return None
    access = data.get("access_token")
    if not isinstance(access, str) or not access.strip():
        return None
    expires_at = data.get("expires_at")
    try:
        exp = int(expires_at) if expires_at is not None else None
    except (TypeError, ValueError):
        exp = None
    if exp is not None:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        # expires_at may be ms or s; treat values < 1e12 as seconds.
        exp_ms = exp if exp > 1_000_000_000_000 else exp * 1000
        if now >= exp_ms:
            return None
    return access.strip()


def revoke_tokens(provider: str) -> None:
    """Remove stored OAuth tokens."""
    kc = _get_keychain()
    kc.delete(f"oauth:{provider}:access_token")
    kc.delete(f"oauth:{provider}:refresh_token")


__all__ = [
    "get_access_token",
    "load_valid_oauth_access_token",
    "poll_for_token",
    "revoke_tokens",
    "start_device_flow",
    "store_tokens",
]
