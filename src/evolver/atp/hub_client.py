"""ATP Hub client — full interface for the Agent Transaction Protocol.

Equivalent to ``evolver/src/atp/hubClient.js``.
Wraps all ATP Hub HTTP calls with retry, structured responses, and
proxy-aware routing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from evolver.config import HTTP_TRANSPORT_TIMEOUT_MS, resolve_hub_url
from evolver.gep.a2a_protocol import build_hub_headers, get_node_id

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_BASE_S = 1.0


def _hub_url(path: str) -> str:
    return f"{resolve_hub_url()}/v1/a2a/atp/{path}"


async def _post(
    path: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout_ms: int = HTTP_TRANSPORT_TIMEOUT_MS,
) -> dict[str, Any]:
    url = _hub_url(path)
    h = build_hub_headers()
    if headers:
        h.update(headers)
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(
                http2=True, timeout=timeout_ms / 1000.0
            ) as client:
                resp = await client.post(url, json=payload, headers=h)
                resp.raise_for_status()
                return {"ok": True, "data": resp.json()}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                last_exc = exc
                await asyncio.sleep(_BACKOFF_BASE_S * (2 ** attempt))
                continue
            return {"ok": False, "error": str(exc), "status": exc.response.status_code}
        except Exception as exc:
            last_exc = exc
            await asyncio.sleep(_BACKOFF_BASE_S * (2 ** attempt))
    return {"ok": False, "error": str(last_exc) if last_exc else "max_retries"}


async def _get(
    path: str,
    params: dict[str, Any] | None = None,
    timeout_ms: int = HTTP_TRANSPORT_TIMEOUT_MS,
) -> dict[str, Any]:
    url = _hub_url(path)
    h = build_hub_headers()
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(
                http2=True, timeout=timeout_ms / 1000.0
            ) as client:
                resp = await client.get(url, params=params, headers=h)
                resp.raise_for_status()
                return {"ok": True, "data": resp.json()}
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                last_exc = exc
                await asyncio.sleep(_BACKOFF_BASE_S * (2 ** attempt))
                continue
            return {"ok": False, "error": str(exc), "status": exc.response.status_code}
        except Exception as exc:
            last_exc = exc
            await asyncio.sleep(_BACKOFF_BASE_S * (2 ** attempt))
    return {"ok": False, "error": str(last_exc) if last_exc else "max_retries"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def place_order(
    service_id: str,
    budget: float,
    requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "sender_id": get_node_id(),
        "service_id": service_id,
        "budget": budget,
        "requirements": requirements or {},
    }
    return await _post("order", payload)


async def submit_delivery(
    order_id: str,
    proof: str,
    result_asset_id: str | None = None,
) -> dict[str, Any]:
    payload = {
        "sender_id": get_node_id(),
        "order_id": order_id,
        "proof": proof,
        "result_asset_id": result_asset_id,
    }
    return await _post("deliver", payload)


async def verify_delivery(
    delivery_id: str,
    verdict: str,
    score: float = 0.0,
) -> dict[str, Any]:
    payload = {
        "sender_id": get_node_id(),
        "delivery_id": delivery_id,
        "verdict": verdict,
        "score": score,
    }
    return await _post("verify", payload)


async def settle_order(order_id: str) -> dict[str, Any]:
    payload = {"sender_id": get_node_id(), "order_id": order_id}
    return await _post("settle", payload)


async def dispute_order(
    order_id: str,
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "sender_id": get_node_id(),
        "order_id": order_id,
        "reason": reason,
        "evidence": evidence or {},
    }
    return await _post("dispute", payload)


async def get_order_status(order_id: str) -> dict[str, Any]:
    return await _get(f"order/{order_id}")


async def get_atp_policy() -> dict[str, Any]:
    return await _get("policy")


async def list_my_tasks() -> dict[str, Any]:
    return await _get("tasks")


async def get_merchant_tier(merchant_id: str | None = None) -> dict[str, Any]:
    params = {}
    if merchant_id:
        params["merchant_id"] = merchant_id
    return await _get("merchant/tier", params=params)


async def list_proofs(order_id: str | None = None) -> dict[str, Any]:
    params = {}
    if order_id:
        params["order_id"] = order_id
    return await _get("proofs", params=params)


async def publish_service(service: dict[str, Any]) -> dict[str, Any]:
    payload = {"sender_id": get_node_id(), **service}
    return await _post("service/publish", payload)


async def update_service(service_id: str, service: dict[str, Any]) -> dict[str, Any]:
    payload = {"sender_id": get_node_id(), "service_id": service_id, **service}
    return await _post("service/update", payload)
