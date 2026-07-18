"""Low-level A2A message protocol + transport registration.

Equivalent to evolver/src/gep/a2aProtocol.js (obfuscated).
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx

from evolver.config import (
    HELLO_TIMEOUT_MS,
    HTTP_TRANSPORT_TIMEOUT_MS,
    HUB_SEARCH_TIMEOUT_MS,
    resolve_hub_url,
)
from evolver.gep.content_hash import compute_asset_id
from evolver.gep.paths import get_evolver_home, get_repo_root

PROTOCOL_NAME = "gep-a2a"
PROTOCOL_VERSION = "1.0.0"
VALID_MESSAGE_TYPES = frozenset({"hello", "publish", "fetch", "report", "decision", "revoke"})
DRY_RUN_NODE_ID = "node_000000000000"


def get_hub_url() -> str | None:
    try:
        return resolve_hub_url()
    except ValueError:
        return None


def get_node_id() -> str | None:
    """Resolve node id (env → persisted → mailbox → mint+persist).

    Matches Node ``getNodeId()``: first call may mint and write
    ``~/.evomap/node_id`` under the canonical identity lock.
    """
    from evolver.gep.node_identity import get_or_create_node_id  # noqa: PLC0415

    return get_or_create_node_id()


def get_hub_node_secret() -> str | None:
    """Resolve Hub node secret from env / identity tuple (no cross-node bleed)."""
    env = (os.environ.get("A2A_NODE_SECRET") or os.environ.get("EVOMAP_NODE_SECRET") or "").strip()
    if env:
        # Prefer explicit env when set; identity tuple still used for version.
        return env
    from evolver.gep.node_identity import resolve_identity_tuple  # noqa: PLC0415

    secret = resolve_identity_tuple(create=False).get("secret")
    return str(secret) if secret else None


def get_hub_node_secret_version() -> str | None:
    raw = os.environ.get("A2A_NODE_SECRET_VERSION") or os.environ.get("EVOMAP_NODE_SECRET_VERSION")
    if raw and str(raw).strip():
        return str(raw).strip()
    from evolver.gep.node_identity import resolve_identity_tuple  # noqa: PLC0415

    version = resolve_identity_tuple(create=False).get("version")
    return str(version) if version is not None else None


def build_hub_headers() -> dict[str, str]:
    secret = get_hub_node_secret()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    return headers


def build_node_scoped_hub_headers(*, create: bool = True) -> dict[str, str]:
    """Node-scoped Hub auth from the active identity tuple."""
    from evolver.gep.node_identity import build_identity_hub_headers  # noqa: PLC0415

    return build_identity_hub_headers(create=create)


def _new_message_id() -> str:
    return f"msg_{int(time.time() * 1000)}_{secrets.token_hex(4)}"


def build_message(
    *,
    message_type: str,
    payload: dict[str, Any] | None = None,
    sender_id: str | None = None,
) -> dict[str, Any]:
    if message_type not in VALID_MESSAGE_TYPES:
        msg = f"Invalid message type: {message_type}"
        raise ValueError(msg)
    return {
        "protocol": PROTOCOL_NAME,
        "protocol_version": PROTOCOL_VERSION,
        "message_type": message_type,
        "message_id": _new_message_id(),
        "sender_id": sender_id or get_node_id() or DRY_RUN_NODE_ID,
        "timestamp": datetime.now(UTC).isoformat(),
        "payload": payload or {},
    }


def build_fetch(
    *,
    asset_type: str | None = None,
    local_id: str | None = None,
    asset_ids: list[str] | None = None,
    signals: list[str] | None = None,
    search_only: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if asset_type:
        payload["asset_type"] = asset_type
    if local_id:
        payload["local_id"] = local_id
    if asset_ids:
        payload["asset_ids"] = asset_ids
    if signals:
        payload["signals"] = signals
    if search_only is True:
        payload["search_only"] = True
    return build_message(message_type="fetch", payload=payload)


def _valid_execution_trace(trace: Any) -> bool:
    return isinstance(trace, list) and len(trace) > 0


def _synthesize_execution_trace(
    capsule: dict[str, Any],
    validation: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if validation and isinstance(validation.get("results"), list):
        steps: list[dict[str, Any]] = []
        for idx, row in enumerate(validation["results"], start=1):
            if not isinstance(row, dict):
                continue
            cmd = str(row.get("cmd") or row.get("command") or "")
            ok = bool(row.get("ok"))
            steps.append({"step": idx, "stage": "validate", "cmd": cmd, "exit": 0 if ok else 1})
        if steps:
            return steps
    outcome_raw = capsule.get("outcome")
    outcome = outcome_raw if isinstance(outcome_raw, dict) else {}
    status = str(outcome.get("status") or "success")
    exit_code = 0 if status == "success" else 1
    return [{"step": 1, "stage": "build", "cmd": "node --test", "exit": exit_code}]


def _bundle_signature(assets: list[dict[str, Any]], secret: str) -> str:
    ids = sorted(
        asset["asset_id"]
        for asset in assets
        if asset.get("type") in ("Gene", "Capsule") and asset.get("asset_id")
    )
    return hmac.new(secret.encode(), "|".join(ids).encode(), hashlib.sha256).hexdigest()


def build_publish_bundle(
    *,
    gene: dict[str, Any],
    capsule: dict[str, Any],
    event: dict[str, Any] | None = None,
    node_id: str | None = None,
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a signed Gene+Capsule(+Event) publish envelope."""
    g = copy.deepcopy(gene)
    c = copy.deepcopy(capsule)
    e = copy.deepcopy(event) if event else None
    if not _valid_execution_trace(c.get("execution_trace")):
        c["execution_trace"] = _synthesize_execution_trace(c, validation)
    assets: list[dict[str, Any]] = [g, c]
    if e is not None:
        assets.append(e)
    for asset in assets:
        asset["asset_id"] = compute_asset_id(asset)
    payload: dict[str, Any] = {"assets": assets}
    secret = get_hub_node_secret()
    if secret:
        payload["signature"] = _bundle_signature(assets, secret)
    return build_message(message_type="publish", payload=payload, sender_id=node_id)


def read_node_id_file(path: os.PathLike[str] | str) -> str:
    try:
        raw = os.fsdecode(path)
        if not os.path.isfile(raw):
            return ""
        return Path(raw).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def non_persisted_node_id() -> str:
    env_id = os.environ.get("A2A_NODE_ID")
    if env_id and env_id.strip():
        return env_id.strip()
    home_id = read_node_id_file(get_evolver_home() / "node_id")
    if home_id:
        return home_id
    repo = get_repo_root()
    if repo:
        repo_id = read_node_id_file(repo / ".evomap_node_id")
        if repo_id:
            return repo_id
    return DRY_RUN_NODE_ID


def post_hub_envelope(
    endpoint_path: str,
    message: dict[str, Any],
    *,
    hub_url: str | None = None,
    headers: dict[str, str] | None = None,
    timeout_ms: int = HTTP_TRANSPORT_TIMEOUT_MS,
) -> dict[str, Any]:
    """Synchronous Hub POST used by CLI contracts."""
    base = (hub_url or get_hub_url() or "").rstrip("/")
    if not base:
        return {"ok": False, "status": 0, "body": {"error": "no_hub_url"}}
    url = f"{base}{endpoint_path}"
    req_headers = headers or build_node_scoped_hub_headers()
    try:
        resp = httpx.post(
            url,
            content=json.dumps(message),
            headers=req_headers,
            timeout=timeout_ms / 1000.0,
        )
        body: Any
        try:
            body = resp.json()
        except json.JSONDecodeError:
            text = resp.text[:200] if resp.text else ""
            body = {"error": text} if text else {}
        return {"ok": resp.is_success, "status": resp.status_code, "body": body}
    except httpx.HTTPError:
        return {"ok": False, "status": 0, "body": {"error": "network_error"}}


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
        return cast(dict[str, Any], response.json())


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

    Returns a dict with ``tasks`` (list[dict[str, Any]]) and metadata.
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
        result = await _http_post(f"{hub}/v1/a2a/tasks", payload, timeout_ms=HUB_SEARCH_TIMEOUT_MS)
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
