"""WebUI REST API routes — complete route matrix for the evolver dashboard.

Equivalent to Node's ``evolver/src/webui/server/routes.js``.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from evolver.gep.asset_store import load_capsules, load_genes, read_all_events
from evolver.webui.observer import (
    call_log_summary,
    calls_by_run,
    cost_index,
    format_interactions,
    get_open_prs,
    get_pr_status,
    get_repo_info,
    health_check,
    health_summary,
    latest_all_commentaries,
    latest_commentary,
    lifecycle_status,
    lifecycle_summary,
    narrative_history,
    narrative_summary,
    personality_data,
    pipeline_insights,
    pipeline_stats,
    pipeline_timeline,
    recent_calls,
    reflection_entries,
    reuse_summary,
    runs_history,
    safety_events,
    serialize_assets,
    skills_health,
    skills_monitor_run,
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


@router.get("/api/insights")
async def api_insights() -> JSONResponse:
    try:
        return _ok(pipeline_insights())
    except Exception as exc:
        return _err(str(exc))


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
# Interactions, Personality, Memory, Asset Call Log
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


@router.get("/api/call-log")
async def api_call_log_summary(
    run_id: str | None = Query(None),
    last: int | None = Query(None, ge=1, le=1000),
) -> JSONResponse:
    try:
        return _ok(call_log_summary(run_id=run_id, last=last))
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/call-log/{run_id}")
async def api_call_log_by_run(run_id: str) -> JSONResponse:
    try:
        return _ok({"run_id": run_id, "entries": calls_by_run(run_id)})
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/asset-reuse")
async def api_asset_reuse(
    run_id: str | None = Query(None),
    last: int | None = Query(None, ge=1, le=1000),
) -> JSONResponse:
    try:
        return _ok(reuse_summary(run_id=run_id, last=last))
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/asset-costs")
async def api_asset_costs() -> JSONResponse:
    try:
        return _ok({"costs": cost_index()})
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/call-log/recent")
async def api_recent_calls(last: int = Query(100, ge=1, le=1000)) -> JSONResponse:
    try:
        return _ok({"entries": recent_calls(last=last)})
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


@router.get("/api/skills/health")
async def api_skills_health() -> JSONResponse:
    try:
        return _ok(skills_health())
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/skills/monitor")
async def api_skills_monitor() -> JSONResponse:
    try:
        return _ok(skills_monitor_run())
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/health")
async def api_health() -> JSONResponse:
    try:
        return _ok(health_check())
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/health/summary")
async def api_health_summary() -> JSONResponse:
    try:
        return _ok(health_summary())
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/lifecycle")
async def api_lifecycle() -> JSONResponse:
    try:
        return _ok(lifecycle_status())
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/lifecycle/summary")
async def api_lifecycle_summary() -> JSONResponse:
    try:
        return _ok(lifecycle_summary())
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/narratives")
async def api_narratives(limit: int = Query(20, ge=1, le=100)) -> JSONResponse:
    try:
        return _ok({"text": narrative_history(limit=limit)})
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/narratives/summary")
async def api_narratives_summary() -> JSONResponse:
    try:
        return _ok(narrative_summary())
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/reflections")
async def api_reflections(limit: int = Query(50, ge=1, le=500)) -> JSONResponse:
    try:
        return _ok({"entries": reflection_entries(limit=limit)})
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/commentary")
async def api_commentary(
    persona: str = Query("pragmatist", pattern="^(pragmatist|explorer|critic)$"),
    verbose: bool = Query(False),
) -> JSONResponse:
    try:
        return _ok(latest_commentary(persona=persona, verbose=verbose))
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/commentary/all")
async def api_commentary_all(verbose: bool = Query(False)) -> JSONResponse:
    try:
        return _ok(latest_all_commentaries(verbose=verbose))
    except Exception as exc:
        return _err(str(exc))


@router.post("/api/trigger")
async def api_trigger() -> JSONResponse:
    """External trigger endpoint — fires a filesystem trigger for evolution."""
    try:
        from evolver.ops.trigger import record_http_trigger

        result = record_http_trigger(source="http")
        return _ok(result)
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/pipeline/stats")
async def api_pipeline_stats() -> JSONResponse:
    try:
        return _ok(pipeline_stats())
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
# GitHub PR status (Sprint 16.2)
# ---------------------------------------------------------------------------


@router.get("/api/github/repo")
async def api_github_repo() -> JSONResponse:
    try:
        return _ok(get_repo_info())
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/github/prs")
async def api_github_prs() -> JSONResponse:
    try:
        return _ok({"data": get_open_prs()})
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/github/pr/{number}")
async def api_github_pr(number: str) -> JSONResponse:
    """PR number is untrusted route input — only a positive integer may proceed."""
    if not re.fullmatch(r"\d+", str(number)):
        return JSONResponse(
            {
                "error": "PR number must be a positive integer",
                "code": "INVALID_PR_NUMBER",
                "number": None,
                "available": False,
                "reason": "invalid_number",
            },
            status_code=400,
        )
    try:
        return _ok(get_pr_status(number))
    except Exception as exc:
        return _err(str(exc))


# ---------------------------------------------------------------------------
# Logs SSE
# ---------------------------------------------------------------------------


@router.get("/api/logs")
async def api_logs(request: Request) -> StreamingResponse:
    """SSE log stream."""
    test_mode = request.headers.get("x-test-mode") == "1"

    async def event_generator() -> AsyncIterator[str]:
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
