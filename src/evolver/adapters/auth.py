"""OAuth device-code login/logout for the EvoMap Hub.

Equivalent to the Node `login` / `logout` commands.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, cast

import httpx

from evolver.config import resolve_hub_url


def _auth_path() -> Path:
    """Return the path to the local auth store."""
    home = Path(os.environ.get("EVOLVER_HOME", Path.home() / ".evolver"))
    return home / "auth.json"


def load_auth() -> dict[str, Any] | None:
    """Load stored auth credentials if present and not expired."""
    path = _auth_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    expires_at = data.get("expires_at")
    if expires_at and time.time() > expires_at:
        return None
    return cast(dict[str, Any], data)


def save_auth(data: dict[str, Any]) -> None:
    """Persist auth credentials to disk."""
    path = _auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def clear_auth() -> bool:
    """Remove stored auth credentials. Returns True if a file was deleted."""
    path = _auth_path()
    if path.exists():
        path.unlink()
        return True
    return False


def _device_code_url(hub_url: str) -> str:
    return f"{hub_url}/v1/auth/device"


def _token_url(hub_url: str) -> str:
    return f"{hub_url}/v1/auth/token"


async def start_device_flow(hub_url: str | None = None) -> dict[str, Any]:
    """Request a device code from the Hub.

    Returns a dict with ``ok``, ``device_code``, ``user_code``,
    ``verification_uri``, ``expires_in``, ``interval``.
    """
    hub = hub_url or resolve_hub_url()
    payload = {"client_id": "evolver-cli", "scope": "read write"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(_device_code_url(hub), json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    return {"ok": True, **data}


async def poll_for_token(
    device_code: str,
    interval: int = 5,
    expires_in: int = 600,
    hub_url: str | None = None,
) -> dict[str, Any]:
    """Poll the Hub token endpoint until success, expiry, or error.

    Returns a dict with ``ok``, ``access_token``, ``token_type``,
    ``expires_in``, and ``hub_url``.
    """
    hub = hub_url or resolve_hub_url()
    deadline = time.time() + expires_in
    payload = {
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "device_code": device_code,
        "client_id": "evolver-cli",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        while time.time() < deadline:
            try:
                resp = await client.post(_token_url(hub), json=payload)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 400:
                    body = (
                        exc.response.json()
                        if exc.response.headers.get("content-type", "").startswith(
                            "application/json"
                        )
                        else {}
                    )
                    if body.get("error") == "authorization_pending":
                        await _async_sleep(interval)
                        continue
                    return {
                        "ok": False,
                        "error": body.get("error_description", body.get("error", str(exc))),
                    }
                return {"ok": False, "error": str(exc)}
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

            access_token = data.get("access_token")
            if access_token:
                expires_in_val = data.get("expires_in", 3600)
                return {
                    "ok": True,
                    "access_token": access_token,
                    "token_type": data.get("token_type", "Bearer"),
                    "expires_at": time.time() + expires_in_val,
                    "hub_url": hub,
                }

            await _async_sleep(interval)

    return {"ok": False, "error": "Device code expired"}


async def _async_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


async def login(
    hub_url: str | None = None,
    mock: bool = False,
) -> dict[str, Any]:
    """Execute the full device-code login flow.

    Returns a dict with ``ok``, ``access_token``, and metadata.
    """
    if mock:
        token = f"mock_{os.urandom(16).hex()}"
        result = {
            "ok": True,
            "access_token": token,
            "token_type": "Bearer",
            "expires_at": time.time() + 3600,
            "hub_url": hub_url or resolve_hub_url(),
        }
        save_auth(result)
        return result

    device = await start_device_flow(hub_url)
    if not device.get("ok"):
        return device

    user_code = device.get("user_code")
    verification_uri = device.get("verification_uri")
    if user_code and verification_uri:
        print(f"\nPlease visit: {verification_uri}")
        print(f"Enter code:   {user_code}\n")

    token_result = await poll_for_token(
        device_code=device["device_code"],
        interval=device.get("interval", 5),
        expires_in=device.get("expires_in", 600),
        hub_url=hub_url,
    )
    if token_result.get("ok"):
        save_auth(token_result)
    return token_result


def logout() -> dict[str, Any]:
    """Clear local auth credentials.

    Returns a dict with ``ok`` and ``was_present``.
    """
    was_present = clear_auth()
    return {"ok": True, "was_present": was_present}
