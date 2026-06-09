"""FastAPI WebUI for evolver runtime observability.

Equivalent to evolver/src/webui/server.js.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

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

app = FastAPI(title="Evolver WebUI", version="1.8.0")


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


@app.get("/genes")
async def genes() -> JSONResponse:
    return JSONResponse({"genes": load_genes()})


@app.get("/capsules")
async def capsules() -> JSONResponse:
    return JSONResponse({"capsules": load_capsules()})
