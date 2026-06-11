"""A2A Proxy server — forwards local A2A traffic to the EvoMap Hub.

Equivalent to evolver/src/proxy/server.js skeleton.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from evolver.adapters.auth import load_auth
from evolver.config import HTTP_TRANSPORT_TIMEOUT_MS, resolve_hub_url
from evolver.gep.a2a_protocol import build_hub_headers
from evolver.gep.paths import get_repo_root
from evolver.proxy.extensions.atp_deliver_loop import AtpDeliverLoop
from evolver.proxy.extensions.dm_handler import create_dm_handler
from evolver.proxy.extensions.session_handler import create_session_handler
from evolver.proxy.extensions.skill_update_loop import SkillUpdateLoop
from evolver.proxy.extensions.skill_updater import create_skill_updater
from evolver.proxy.extensions.trace_control import create_trace_control
from evolver.proxy.lifecycle.manager import LifecycleManager
from evolver.proxy.mailbox.store import MailboxStore
from evolver.proxy.server.routes import router
from evolver.proxy.task.monitor import TaskMonitor
from evolver.proxy.trace import get_trace_store

logger = logging.getLogger(__name__)


def _lifecycle_enabled() -> bool:
    return os.environ.get("EVOLVER_PROXY_LIFECYCLE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


@asynccontextmanager
async def _proxy_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialize mailbox, session, task monitor, and ATP local state."""
    root = get_repo_root() or Path.cwd()
    mailbox_dir = root / ".evolver" / "proxy-mailbox"
    mailbox_store = MailboxStore(mailbox_dir)
    _app.state.mailbox_store = mailbox_store
    _app.state.session_handler = create_session_handler()
    _app.state.task_monitor = TaskMonitor()
    _app.state.dm_handler = create_dm_handler()
    skill_updater = create_skill_updater(mailbox_store=mailbox_store)
    _app.state.skill_updater = skill_updater
    _app.state.trace_control = create_trace_control()
    _app.state.atp_orders = {}
    _app.state.atp_proofs = []
    _app.state.claimed_tasks = {}

    lifecycle = LifecycleManager(store=mailbox_store)
    _app.state.lifecycle_manager = lifecycle
    if _lifecycle_enabled():
        try:
            hello = await lifecycle.hello()
            if hello.get("ok"):
                lifecycle.start_heartbeat_loop()
            else:
                logger.warning("[Proxy] Lifecycle hello failed: %s", hello.get("error"))
        except Exception as exc:
            logger.warning("[Proxy] Lifecycle hello error: %s", exc)

    skill_loop = SkillUpdateLoop(skill_updater)
    skill_loop.start()
    _app.state.skill_update_loop = skill_loop

    atp_loop = AtpDeliverLoop()
    atp_loop.start()
    _app.state.atp_deliver_loop = atp_loop

    yield

    atp_loop.stop()
    lifecycle.stop_heartbeat_loop()
    skill_loop.stop()


app = FastAPI(title="Evolver A2A Proxy", version="1.0.0", lifespan=_proxy_lifespan)
app.include_router(router, prefix="/v1/a2a")

async def _forward_to_hub(
    path: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout_ms: int = HTTP_TRANSPORT_TIMEOUT_MS,
) -> dict[str, Any]:
    hub = resolve_hub_url()
    url = f"{hub}/v1/a2a/{path}"
    auth = load_auth()
    fwd_headers = build_hub_headers()
    if auth:
        fwd_headers["Authorization"] = f"Bearer {auth['access_token']}"
    if headers:
        fwd_headers.update(
            {k: v for k, v in headers.items() if k.lower() not in ("host", "content-length")}
        )

    start = time.time()
    try:
        async with httpx.AsyncClient(http2=True, timeout=timeout_ms / 1000.0) as client:
            response = await client.post(url, json=payload, headers=fwd_headers)
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPStatusError as exc:
        body = (
            exc.response.json()
            if exc.response.headers.get("content-type", "").startswith("application/json")
            else {"error": str(exc)}
        )
        get_trace_store().push(
            {"ts": start, "path": path, "status": exc.response.status_code, "error": body}
        )
        return {"ok": False, "error": body, "status_code": exc.response.status_code}
    except Exception as exc:
        get_trace_store().push({"ts": start, "path": path, "status": None, "error": str(exc)})
        return {"ok": False, "error": str(exc)}

    elapsed_ms = int((time.time() - start) * 1000)
    get_trace_store().push({"ts": start, "path": path, "status": 200, "elapsed_ms": elapsed_ms})
    return {"ok": True, "hub_response": body, "elapsed_ms": elapsed_ms}


@app.post("/v1/a2a/proxy/{path:path}")
async def proxy_post(path: str, request: Request) -> JSONResponse:
    """Forward an arbitrary A2A POST to the Hub."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)

    result = await _forward_to_hub(path, payload)
    status = result.pop("status_code", 200) if result.get("ok") else result.pop("status_code", 502)
    return JSONResponse(result, status_code=status)


@app.get("/v1/a2a/health")
async def health() -> JSONResponse:
    store = get_trace_store()
    return JSONResponse({"status": "ok", "trace_count": store.count()})


@app.get("/v1/a2a/trace")
async def trace(limit: int = 50) -> JSONResponse:
    return JSONResponse({"trace": get_trace_store().recent(limit)})
