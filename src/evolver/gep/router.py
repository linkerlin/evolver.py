"""A2A message router — forwards messages to local or remote peers.

Equivalent to a skeleton of evolver/src/gep/router.js.
"""

from __future__ import annotations

from typing import Any

import httpx

from evolver.config import HTTP_TRANSPORT_TIMEOUT_MS
from evolver.gep.a2a_protocol import build_hub_headers, get_node_id
from evolver.gep.discovery import get_peer_endpoint


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
