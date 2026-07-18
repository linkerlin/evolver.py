"""ATP (Agent Task Protocol) marketplace client.

Provides buy, list-orders, verify, and complete operations against the Hub.
"""

from __future__ import annotations

from typing import Any

import httpx

from evolver.adapters.auth import load_auth
from evolver.config import resolve_hub_base
from evolver.gep.a2a_protocol import build_hub_headers


def _atp_url(hub_url: str, path: str) -> str:
    return f"{hub_url.rstrip('/')}/v1/atp/{path}"


def _auth_headers() -> dict[str, str]:
    headers = build_hub_headers()
    auth = load_auth()
    if auth:
        headers["Authorization"] = f"Bearer {auth['access_token']}"
    return headers


async def buy(
    skill_id: str,
    quantity: int = 1,
    hub_url: str | None = None,
) -> dict[str, Any]:
    """Place an order for a skill on the ATP marketplace."""
    try:
        hub = resolve_hub_base(hub_url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "stage": "tls"}
    payload = {"skill_id": skill_id, "quantity": quantity}
    try:
        async with httpx.AsyncClient(http2=True, timeout=15.0) as client:
            resp = await client.post(
                _atp_url(hub, "orders"),
                json=payload,
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "order": data}


async def list_orders(
    status: str | None = None,
    limit: int = 20,
    hub_url: str | None = None,
) -> dict[str, Any]:
    """List ATP orders for the authenticated node."""
    try:
        hub = resolve_hub_base(hub_url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "stage": "tls"}
    params: dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = status
    try:
        async with httpx.AsyncClient(http2=True, timeout=15.0) as client:
            resp = await client.get(
                _atp_url(hub, "orders"),
                params=params,
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "orders": data.get("orders", [])}


async def verify_delivery(
    order_id: str,
    approval: bool = True,
    hub_url: str | None = None,
) -> dict[str, Any]:
    """Verify (approve or reject) an ATP delivery."""
    try:
        hub = resolve_hub_base(hub_url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "stage": "tls"}
    payload = {"approved": approval}
    try:
        async with httpx.AsyncClient(http2=True, timeout=15.0) as client:
            resp = await client.post(
                _atp_url(hub, f"orders/{order_id}/verify"),
                json=payload,
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "result": data}


async def complete_task(
    task_id: str,
    result_payload: dict[str, Any] | None = None,
    hub_url: str | None = None,
) -> dict[str, Any]:
    """Mark an ATP task as completed and submit results."""
    try:
        hub = resolve_hub_base(hub_url)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "stage": "tls"}
    payload = result_payload or {"status": "completed"}
    try:
        async with httpx.AsyncClient(http2=True, timeout=15.0) as client:
            resp = await client.post(
                _atp_url(hub, f"tasks/{task_id}/complete"),
                json=payload,
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "result": data}
