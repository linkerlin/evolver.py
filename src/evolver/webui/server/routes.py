"""WebUI REST API routes — complete route matrix for the evolver dashboard.

Equivalent to Node's ``evolver/src/webui/server/routes.js``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from evolver.gep.asset_store import load_capsules, load_genes, read_all_events
from evolver.webui.observer import (
    format_interactions,
    personality_data,
    pipeline_timeline,
    redact_text,
    runs_history,
    safety_events,
    serialize_assets,
    skills_status,
    system_status,
)

router = APIRouter()


def _ok(data: dict[str, Any]) -> JSONResponse:
    return JSONResponse(data)


def _err(message: str, code: str = "internal_error") -> JSONResponse:
    return JSONResponse({"error": message, "code": code}, status_code=500)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@router.get("/api/status")
async def api_status() -> JSONResponse:
    try:
        return _ok(system_status())
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


@router.get("/api/assets")
async def api_assets(
    type: str | None = Query(None, description="Filter by 'gene' or 'capsule'"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    q: str | None = Query(None, description="Search query"),
) -> JSONResponse:
    try:
        return _ok(serialize_assets(type_filter=type, page=page, limit=limit, query=q))
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/assets/{asset_id}")
async def api_asset_detail(asset_id: str) -> JSONResponse:
    """Return a single asset by ID."""
    try:
        for g in load_genes():
            if g.get("id") == asset_id:
                return _ok({"type": "gene", **g})
        for c in load_capsules():
            if c.get("id") == asset_id:
                return _ok({"type": "capsule", **c})
        return JSONResponse({"error": "Asset not found", "code": "not_found"}, status_code=404)
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Candidates, Calls, Lineage
# ---------------------------------------------------------------------------


@router.get("/api/candidates")
async def api_candidates() -> JSONResponse:
    """Return candidate genes (not yet solidified)."""
    try:
        genes = load_genes()
        candidates = [g for g in genes if not g.get("solidified", False)]
        return _ok({"candidates": candidates})
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/calls")
async def api_calls(limit: int = Query(100, ge=1, le=1000)) -> JSONResponse:
    """Return asset invocation logs."""
    try:
        events = read_all_events()
        calls = [e for e in events if e.get("type") == "invoke"][-limit:]
        return _ok({"calls": calls})
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/lineage")
async def api_lineage(gene_id: str | None = Query(None)) -> JSONResponse:
    """Return gene → capsule → event lineage."""
    try:
        genes = {g["id"]: g for g in load_genes() if "id" in g}
        capsules = load_capsules()
        events = read_all_events()
        lineage: list[dict[str, Any]] = []
        target = gene_id
        if target and target in genes:
            lineage.append({"type": "gene", **genes[target]})
            for cap in capsules:
                if cap.get("gene_id") == target:
                    lineage.append({"type": "capsule", **cap})
                    cap_id = cap.get("id")
                    for evt in events:
                        if evt.get("capsule_id") == cap_id:
                            lineage.append({"type": "event", **evt})
        return _ok({"lineage": lineage, "gene_id": target})
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Interactions, Personality, Memory
# ---------------------------------------------------------------------------


@router.get("/api/interactions")
async def api_interactions(limit: int = Query(100, ge=1, le=500)) -> JSONResponse:
    try:
        return _ok({"interactions": format_interactions(limit=limit)})
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/personality")
async def api_personality() -> JSONResponse:
    try:
        return _ok(personality_data())
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/memory-graph")
async def api_memory_graph(limit: int = Query(100, ge=1, le=1000)) -> JSONResponse:
    try:
        from evolver.gep.memory_graph import read_all

        return _ok({"entries": read_all()[-limit:]})
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Skills, Safety, Runs
# ---------------------------------------------------------------------------


@router.get("/api/skills")
async def api_skills() -> JSONResponse:
    try:
        return _ok(skills_status())
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/safety")
async def api_safety(limit: int = Query(100, ge=1, le=500)) -> JSONResponse:
    try:
        return _ok(safety_events(limit=limit))
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/runs")
async def api_runs(limit: int = Query(50, ge=1, le=200)) -> JSONResponse:
    try:
        return _ok(runs_history(limit=limit))
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Pipeline timeline
# ---------------------------------------------------------------------------


@router.get("/api/pipelines")
async def api_pipelines(limit: int = Query(100, ge=1, le=500)) -> JSONResponse:
    try:
        return _ok({"timeline": pipeline_timeline(limit=limit)})
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Logs SSE
# ---------------------------------------------------------------------------


@router.get("/api/logs")
async def api_logs(request: Request) -> StreamingResponse:
    """SSE log stream."""
    test_mode = request.headers.get("x-test-mode") == "1"

    async def event_generator():
        known = len(read_all_events())
        pings = 0
        while True:
            await asyncio.sleep(0.1 if test_mode else 2.0)
            events = read_all_events()
            if len(events) > known:
                for evt in events[known:]:
                    yield f"data: {json.dumps(evt)}\n\n"
                known = len(events)
            else:
                yield ":ping\n\n"
                pings += 1
                if test_mode and pings >= 2:
                    break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
