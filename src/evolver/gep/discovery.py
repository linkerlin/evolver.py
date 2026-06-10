"""Node discovery for distributed A2A networking.

Equivalent to a skeleton of evolver/src/gep/discovery.js.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from evolver.config import resolve_hub_url
from evolver.gep.a2a_protocol import build_hub_headers, get_node_id

_PEERS: dict[str, dict[str, Any]] = {}
_PEERS_TTL_SEC = 300


def _peers_path() -> Path:
    home = Path(os.environ.get("EVOLVER_HOME", Path.home() / ".evolver"))
    return home / "peers.json"


def load_peers() -> dict[str, dict[str, Any]]:
    """Load persisted peers from disk."""
    path = _peers_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_peers(peers: dict[str, dict[str, Any]] | None = None) -> None:
    """Persist peers to disk."""
    path = _peers_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(peers or _PEERS, indent=2) + "\n", encoding="utf-8")


def add_peer(node_id: str, endpoint: str, metadata: dict[str, Any] | None = None) -> None:
    """Add or update a peer in the local registry."""
    _PEERS[node_id] = {
        "endpoint": endpoint,
        "last_seen": time.time(),
        "metadata": metadata or {},
    }


def remove_peer(node_id: str) -> bool:
    """Remove a peer. Returns True if it existed."""
    return _PEERS.pop(node_id, None) is not None


def list_peers() -> list[dict[str, Any]]:
    """Return a list of known peers, filtering out stale entries."""
    now = time.time()
    active = []
    stale: list[str] = []
    for nid, info in _PEERS.items():
        age = now - info.get("last_seen", 0)
        if age > _PEERS_TTL_SEC:
            stale.append(nid)
        else:
            active.append({"node_id": nid, **info})
    for nid in stale:
        _PEERS.pop(nid, None)
    return active


def get_peer_endpoint(node_id: str) -> str | None:
    """Return the HTTP endpoint for a given peer, or None."""
    info = _PEERS.get(node_id)
    return info["endpoint"] if info else None


async def discover_peers(hub_url: str | None = None) -> dict[str, Any]:
    """Fetch active peers from the EvoMap Hub."""
    hub = hub_url or resolve_hub_url()
    try:
        async with httpx.AsyncClient(http2=True, timeout=15.0) as client:
            resp = await client.get(
                f"{hub}/v1/a2a/peers",
                headers=build_hub_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    peers = data.get("peers", [])
    for p in peers:
        nid = p.get("node_id")
        endpoint = p.get("endpoint")
        if nid and endpoint:
            add_peer(nid, endpoint, p.get("metadata", {}))
    save_peers()
    return {"ok": True, "peers": list_peers()}


async def check_peer_health(
    node_id: str,
    timeout_sec: float = 5.0,
) -> dict[str, Any]:
    """Probe a peer's /v1/a2a/health endpoint and record latency."""
    endpoint = get_peer_endpoint(node_id)
    if not endpoint:
        return {"ok": False, "error": "unknown peer", "latency_ms": None}
    url = f"{endpoint}/v1/a2a/health"
    start = time.time()
    try:
        async with httpx.AsyncClient(http2=True, timeout=timeout_sec) as client:
            resp = await client.get(url, headers=build_hub_headers())
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "latency_ms": int((time.time() - start) * 1000)}
    latency_ms = int((time.time() - start) * 1000)
    return {"ok": True, "latency_ms": latency_ms, "data": data}


async def register_with_hub(
    endpoint: str,
    hub_url: str | None = None,
) -> dict[str, Any]:
    """Register this node's endpoint with the Hub."""
    hub = hub_url or resolve_hub_url()
    payload = {
        "node_id": get_node_id(),
        "endpoint": endpoint,
        "timestamp": time.time(),
    }
    try:
        async with httpx.AsyncClient(http2=True, timeout=15.0) as client:
            resp = await client.post(
                f"{hub}/v1/a2a/register",
                json=payload,
                headers=build_hub_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "hub_response": data}
