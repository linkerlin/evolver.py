"""A2A Proxy server — forwards local A2A traffic to the EvoMap Hub.

Equivalent to evolver/src/proxy/server.js skeleton.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from evolver.adapters.auth import load_auth
from evolver.config import HTTP_TRANSPORT_TIMEOUT_MS, resolve_hub_url
from evolver.gep.a2a_protocol import build_hub_headers

app = FastAPI(title="Evolver A2A Proxy", version="1.0.0")

# In-memory request trace (last N entries)
_trace: list[dict[str, Any]] = []
_MAX_TRACE = 100


def _push_trace(entry: dict[str, Any]) -> None:
    _trace.append(entry)
    if len(_trace) > _MAX_TRACE:
        _trace.pop(0)


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
        fwd_headers.update({k: v for k, v in headers.items() if k.lower() not in ("host", "content-length")})

    start = time.time()
    try:
        async with httpx.AsyncClient(http2=True, timeout=timeout_ms / 1000.0) as client:
            response = await client.post(url, json=payload, headers=fwd_headers)
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPStatusError as exc:
        body = exc.response.json() if exc.response.headers.get("content-type", "").startswith("application/json") else {"error": str(exc)}
        _push_trace({"ts": start, "path": path, "status": exc.response.status_code, "error": body})
        return {"ok": False, "error": body, "status_code": exc.response.status_code}
    except Exception as exc:
        _push_trace({"ts": start, "path": path, "status": None, "error": str(exc)})
        return {"ok": False, "error": str(exc)}

    elapsed_ms = int((time.time() - start) * 1000)
    _push_trace({"ts": start, "path": path, "status": 200, "elapsed_ms": elapsed_ms})
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
    return JSONResponse({"status": "ok", "trace_count": len(_trace)})


@app.get("/v1/a2a/trace")
async def trace(limit: int = 50) -> JSONResponse:
    return JSONResponse({"trace": _trace[-limit:]})
