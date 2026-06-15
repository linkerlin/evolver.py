"""Directory client — interact with the EvoMap directory service.

Equivalent to ``evolver/src/gep/directoryClient.js`` (101 lines).

Provides node discovery (find nearby nodes for P2P collaboration) and
service registration (advertise local capabilities to the network).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from evolver.config import resolve_hub_url
from evolver.gep.a2a_protocol import build_hub_headers, get_node_id

logger = logging.getLogger(__name__)

_TIMEOUT = 10.0


def _directory_url(path: str) -> str:
    return f"{resolve_hub_url()}/v1/a2a/directory/{path}"


async def register_service(
    service_type: str,
    capabilities: list[str],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Register a local service with the directory."""
    payload = {
        "node_id": get_node_id(),
        "service_type": service_type,
        "capabilities": capabilities,
        "metadata": metadata or {},
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _directory_url("register"),
                json=payload,
                headers=build_hub_headers(),
            )
            resp.raise_for_status()
            return {"ok": True, "data": resp.json()}
    except Exception as exc:
        logger.warning("[directory] register failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def discover_nodes(
    service_type: str | None = None,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """Discover nearby nodes offering a given service type."""
    params: dict[str, Any] = {"limit": limit}
    if service_type:
        params["service_type"] = service_type
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                _directory_url("nodes"),
                params=params,
                headers=build_hub_headers(),
            )
            resp.raise_for_status()
            return {"ok": True, "data": resp.json()}
    except Exception as exc:
        logger.warning("[directory] discover failed: %s", exc)
        return {"ok": False, "error": str(exc)}


async def deregister_service(service_type: str) -> dict[str, Any]:
    """Remove a local service registration."""
    payload = {"node_id": get_node_id(), "service_type": service_type}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _directory_url("deregister"),
                json=payload,
                headers=build_hub_headers(),
            )
            resp.raise_for_status()
            return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


__all__ = ["deregister_service", "discover_nodes", "register_service"]
