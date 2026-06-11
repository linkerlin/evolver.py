"""ATP consumer agent template.

Equivalent to ``evolver/src/atp/consumerAgent.js``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from evolver.atp.hub_client import (
    dispute_order,
    get_atp_policy,
    get_order_status,
    place_order,
    settle_order,
    submit_delivery,
    verify_delivery,
)
from evolver.gep.a2a_protocol import send_hello

logger = logging.getLogger(__name__)

_INITIALIZED = False


async def _ensure_initialized() -> None:
    global _INITIALIZED
    if not _INITIALIZED:
        await send_hello()
        _INITIALIZED = True


async def order_service(
    service_id: str,
    budget: float,
    requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    await _ensure_initialized()
    return await place_order(service_id, budget, requirements)


async def confirm_delivery(order_id: str, approval: bool = True) -> dict[str, Any]:
    await _ensure_initialized()
    return await verify_delivery(order_id, "confirmed" if approval else "rejected")


async def request_ai_judge(order_id: str) -> dict[str, Any]:
    await _ensure_initialized()
    return await verify_delivery(order_id, "ai_judge")


async def settle(order_id: str) -> dict[str, Any]:
    await _ensure_initialized()
    return await settle_order(order_id)


async def dispute(order_id: str, reason: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    await _ensure_initialized()
    return await dispute_order(order_id, reason, evidence)


async def check_order(order_id: str) -> dict[str, Any]:
    await _ensure_initialized()
    return await get_order_status(order_id)


async def get_policy() -> dict[str, Any]:
    await _ensure_initialized()
    return await get_atp_policy()


async def order_and_wait(
    service_id: str,
    budget: float,
    requirements: dict[str, Any] | None = None,
    *,
    poll_interval_s: float = 10.0,
    timeout_s: float = 300.0,
) -> dict[str, Any]:
    """Place an order and block until it settles or times out."""
    result = await order_service(service_id, budget, requirements)
    if not result.get("ok"):
        return result
    order_id = result.get("data", {}).get("order_id")
    if not order_id:
        return {"ok": False, "error": "no_order_id"}

    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        status = await check_order(order_id)
        if not status.get("ok"):
            await asyncio.sleep(poll_interval_s)
            continue
        s = status.get("data", {}).get("status", "")
        if s in ("settled", "verified"):
            return {"ok": True, "order_id": order_id, "status": s}
        if s == "disputed":
            return {"ok": False, "order_id": order_id, "status": s, "error": "order_disputed"}
        await asyncio.sleep(poll_interval_s)

    return {"ok": False, "order_id": order_id, "error": "timeout"}
