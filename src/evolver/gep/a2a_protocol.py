"""Low-level A2A message protocol + transport registration.

Equivalent to evolver/src/gep/a2aProtocol.js (obfuscated).
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx

from evolver.config import (
    HELLO_TIMEOUT_MS,
    HTTP_TRANSPORT_TIMEOUT_MS,
    HUB_SEARCH_TIMEOUT_MS,
    resolve_hub_url,
)


def get_hub_url() -> str | None:
    try:
        return resolve_hub_url()
    except ValueError:
        return None


def get_node_id() -> str | None:
    return os.environ.get("A2A_NODE_ID")


def get_hub_node_secret() -> str | None:
    return os.environ.get("A2A_NODE_SECRET")


def build_hub_headers() -> dict[str, str]:
    secret = get_hub_node_secret()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    return headers


async def _http_post(
    url: str,
    payload: dict[str, Any],
    timeout_ms: int = HTTP_TRANSPORT_TIMEOUT_MS,
) -> dict[str, Any]:
    """POST JSON to the Hub and return parsed response."""
    headers = build_hub_headers()
    async with httpx.AsyncClient(http2=True, timeout=timeout_ms / 1000.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


async def send_hello() -> dict[str, Any]:
    """Send a hello/registration ping to the Hub."""
    hub = get_hub_url()
    if not hub:
        return {"ok": False, "error": "no_hub_url"}
    payload = {
        "type": "hello",
        "node_id": get_node_id(),
        "protocol": "gep-a2a",
        "protocol_version": "1.0.0",
        "timestamp": asyncio.get_event_loop().time(),
    }
    try:
        result = await _http_post(f"{hub}/v1/a2a/hello", payload, timeout_ms=HELLO_TIMEOUT_MS)
        return {"ok": True, "hub_response": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def send_heartbeat() -> dict[str, Any]:
    """Send a heartbeat ping to the Hub."""
    hub = get_hub_url()
    if not hub:
        return {"ok": False, "error": "no_hub_url"}
    payload = {
        "type": "heartbeat",
        "node_id": get_node_id(),
        "timestamp": asyncio.get_event_loop().time(),
    }
    try:
        result = await _http_post(f"{hub}/v1/a2a/heartbeat", payload)
        return {"ok": True, "hub_response": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def fetch_tasks(
    limit: int = 10,
    signals: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch open tasks from the Hub.

    Returns a dict with ``tasks`` (list[dict]) and metadata.
    """
    hub = get_hub_url()
    if not hub:
        return {"ok": False, "error": "no_hub_url", "tasks": []}
    payload: dict[str, Any] = {
        "type": "fetch_tasks",
        "node_id": get_node_id(),
        "limit": limit,
    }
    if signals:
        payload["signals"] = signals
    try:
        result = await _http_post(
            f"{hub}/v1/a2a/tasks", payload, timeout_ms=HUB_SEARCH_TIMEOUT_MS
        )
        tasks = result.get("tasks", [])
        if not isinstance(tasks, list):
            tasks = []
        return {"ok": True, "tasks": tasks, "hub_response": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "tasks": []}


async def submit_task_result(
    task_id: str,
    result_payload: dict[str, Any],
) -> dict[str, Any]:
    """Submit a completed task result back to the Hub."""
    hub = get_hub_url()
    if not hub:
        return {"ok": False, "error": "no_hub_url"}
    payload = {
        "type": "task_result",
        "node_id": get_node_id(),
        "task_id": task_id,
        "result": result_payload,
    }
    try:
        result = await _http_post(f"{hub}/v1/a2a/tasks/{task_id}/result", payload)
        return {"ok": True, "hub_response": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def consume_hub_events(
    max_events: int = 100,
    timeout_ms: int = HTTP_TRANSPORT_TIMEOUT_MS,
) -> dict[str, Any]:
    """Poll the Hub for events directed at this node."""
    hub = get_hub_url()
    if not hub:
        return {"ok": False, "error": "no_hub_url", "events": []}
    payload = {
        "type": "consume_events",
        "node_id": get_node_id(),
        "max_events": max_events,
    }
    try:
        result = await _http_post(f"{hub}/v1/a2a/events", payload, timeout_ms=timeout_ms)
        events = result.get("events", [])
        if not isinstance(events, list):
            events = []
        return {"ok": True, "events": events, "hub_response": result}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "events": []}
