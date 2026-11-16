"""A2A message router — forwards messages to local or remote peers.

Equivalent to a skeleton of evolver/src/gep/router.js.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

import httpx

from evolver.config import HTTP_TRANSPORT_TIMEOUT_MS
from evolver.gep.a2a_protocol import build_hub_headers, get_node_id
from evolver.gep.discovery import get_peer_endpoint

TIER_COST_WEIGHTS: Final[dict[str, float]] = {
    "cheap": 1.0,
    "mid": 2.83,
    "expensive": 6.67,
}
REASONING_MULTIPLIERS: Final[dict[str, float]] = {
    "off": 1.0,
    "low": 1.5,
    "medium": 3.0,
    "high": 6.0,
}


def compute_routing_advice(
    gene: Mapping[str, Any] | None,
    *,
    consecutive_failures: int = 0,
) -> dict[str, Any]:
    """Resolve effective compute tier & cost weight from ``Gene.routing_hint`` (S-8a).

    Escalates one tier when ``consecutive_failures >= 2`` so stubborn multi-round
    failures automatically graduate from cheap/mid to higher reasoning tiers.
    """
    raw_hint = gene.get("routing_hint") if isinstance(gene, Mapping) else None
    hint = raw_hint if isinstance(raw_hint, Mapping) else {}
    base_tier = str(hint.get("tier") or "mid").lower()
    if base_tier not in TIER_COST_WEIGHTS:
        base_tier = "mid"
    base_level = str(hint.get("reasoning_level") or "medium").lower()
    if base_level not in REASONING_MULTIPLIERS:
        base_level = "medium"

    tier_order = ("cheap", "mid", "expensive")
    idx = tier_order.index(base_tier)
    escalated = False
    if consecutive_failures >= 2 and idx < len(tier_order) - 1:
        idx += 1
        escalated = True
        if base_level == "off":
            base_level = "low"
        elif base_level == "low":
            base_level = "medium"
        elif base_level == "medium":
            base_level = "high"

    eff_tier = tier_order[idx]
    weight = TIER_COST_WEIGHTS[eff_tier]
    return {
        "tier": eff_tier,
        "reasoning_level": base_level,
        "tier_weight": weight,
        "escalated": escalated,
        "consecutive_failures": max(0, int(consecutive_failures)),
    }


async def route_message(
    target_node_id: str,
    payload: dict[str, Any],
    timeout_ms: int = HTTP_TRANSPORT_TIMEOUT_MS,
) -> dict[str, Any]:
    """Route a message to *target_node_id*.

    If the target is the local node, return a local-delivery marker.
    Otherwise forward via HTTP POST to the peer's endpoint.
    """
    local_id = get_node_id()
    if local_id and target_node_id == local_id:
        return {"ok": True, "local": True, "delivered": True}

    endpoint = get_peer_endpoint(target_node_id)
    if not endpoint:
        return {"ok": False, "error": f"No route to {target_node_id}"}

    url = f"{endpoint}/v1/a2a/receive"
    try:
        async with httpx.AsyncClient(http2=True, timeout=timeout_ms / 1000.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers=build_hub_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    return {"ok": True, "remote": True, "hub_response": data}
