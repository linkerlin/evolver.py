"""FastAPI WebUI for evolver runtime observability.

Equivalent to evolver/src/webui/server.js.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from evolver.gep.asset_store import (
    load_capsules,
    load_genes,
    read_all_events,
    read_json_if_exists,
)
from evolver.gep.paths import (
    get_evolution_dir,
    get_solidify_state_path,
)
from evolver.webui.dashboard import render_dashboard
from evolver.webui.server.routes import router as api_router

app = FastAPI(title="Evolver WebUI", version="1.8.0")
app.include_router(api_router)

_SSE_POLL_INTERVAL = 2.0  # seconds

# Active WebSocket connections
_ws_connections: set[WebSocket] = set()


async def _ws_broadcast(message: dict[str, Any]) -> None:
    """Broadcast a JSON message to all connected WebSocket clients."""
    text = json.dumps(message)
    disconnected: set[WebSocket] = set()
    for ws in _ws_connections:
        try:
            await ws.send_text(text)
        except Exception:
            disconnected.add(ws)
    for ws in disconnected:
        _ws_connections.discard(ws)


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    return render_dashboard()


@app.get("/status")
async def status() -> JSONResponse:
    solidify = read_json_if_exists(get_solidify_state_path()) or {}
    last_run = solidify.get("last_run")
    last_solidify = solidify.get("last_solidify")
    events = read_all_events()
    return JSONResponse({
        "solidify_pending": last_run is not None and last_solidify is None,
        "last_run": last_run,
        "last_solidify": last_solidify,
        "total_events": len(events),
        "recent_event_ids": [e.get("id") for e in events[-5:]],
    })


@app.get("/events")
async def events(limit: int = 100) -> JSONResponse:
    all_events = read_all_events()
    return JSONResponse({"events": all_events[-limit:]})


@app.get("/events/replay")
async def events_replay(since_id: int = 0, limit: int = 100) -> JSONResponse:
    from evolver.ops.sqlite_store import read_events_replay
    events = read_events_replay(since_id, limit)
    return JSONResponse({"events": events, "since_id": since_id})


@app.get("/events/stream")
async def events_stream(request: Request) -> StreamingResponse:
    """SSE endpoint that pushes new events as they appear."""
    test_mode = request.headers.get("x-test-mode") == "1"

    async def event_generator():
        known = len(read_all_events())
        pings = 0
        while True:
            await asyncio.sleep(0.1 if test_mode else _SSE_POLL_INTERVAL)
            all_events = read_all_events()
            if len(all_events) > known:
                for evt in all_events[known:]:
                    yield f"data: {json.dumps(evt)}\n\n"
                known = len(all_events)
            else:
                # Keep-alive comment to prevent proxy timeouts
                yield ":ping\n\n"
                pings += 1
                if test_mode and pings >= 2:
                    break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/genes")
async def genes() -> JSONResponse:
    return JSONResponse({"genes": load_genes()})


@app.get("/capsules")
async def capsules() -> JSONResponse:
    return JSONResponse({"capsules": load_capsules()})


@app.get("/api/peers")
async def api_peers() -> JSONResponse:
    from evolver.gep.discovery import list_peers
    return JSONResponse({"peers": list_peers()})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Bidirectional WebSocket for real-time control and updates."""
    await websocket.accept()
    _ws_connections.add(websocket)
    try:
        await websocket.send_text(json.dumps({"type": "connected", "clients": len(_ws_connections)}))
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({"type": "error", "message": "invalid JSON"}))
                continue

            action = msg.get("action")
            if action == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            elif action == "run":
                from evolver.ops.auth_middleware import ws_require_role
                ws_require_role(websocket, "admin")
                await _ws_broadcast({"type": "status", "message": "Running evolution cycle..."})
                try:
                    from evolver.evolve import run
                    await run()
                    await _ws_broadcast({"type": "status", "message": "Cycle complete."})
                except Exception as exc:
                    await _ws_broadcast({"type": "error", "message": str(exc)})
            elif action == "solidify":
                from evolver.ops.auth_middleware import ws_require_role
                ws_require_role(websocket, "admin")
                await _ws_broadcast({"type": "status", "message": "Applying solidify..."})
                try:
                    from evolver.gep.solidify import solidify
                    result = solidify()
                    if result.get("ok"):
                        await _ws_broadcast({"type": "status", "message": f"Solidify succeeded: {result.get('event_id')}"})
                    else:
                        await _ws_broadcast({"type": "error", "message": result.get("error", "unknown")})
                except Exception as exc:
                    await _ws_broadcast({"type": "error", "message": str(exc)})
            elif action == "status":
                solidify = read_json_if_exists(get_solidify_state_path()) or {}
                last_run = solidify.get("last_run")
                last_solidify = solidify.get("last_solidify")
                await websocket.send_text(json.dumps({
                    "type": "status",
                    "solidify_pending": last_run is not None and last_solidify is None,
                    "total_events": len(read_all_events()),
                }))
            else:
                await websocket.send_text(json.dumps({"type": "error", "message": f"Unknown action: {action}"}))
    except WebSocketDisconnect:
        _ws_connections.discard(websocket)
    except Exception:
        _ws_connections.discard(websocket)
        raise
