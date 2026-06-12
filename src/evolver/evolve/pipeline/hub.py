"""Hub phase: coordinate with EvoMap Hub / local Proxy.

Equivalent to evolver/src/evolve/pipeline/hub.js.
"""

from __future__ import annotations

import time
from typing import Any

from evolver.gep.a2a_protocol import fetch_tasks
from evolver.gep.autopoiesis import consume_skip_hub_flag


def _apply_hub_payload(ctx: dict[str, Any], result: dict[str, Any]) -> None:
    hub_response = result.get("hub_response")
    if isinstance(hub_response, dict):
        ctx["hub_response"] = hub_response
        if hub_response.get("service_hits"):
            ctx["hub_service_hits"] = hub_response["service_hits"]
        if hub_response.get("assets"):
            ctx["hub_assets"] = hub_response["assets"]
    elif result.get("ok"):
        ctx["hub_response"] = {k: v for k, v in result.items() if k != "tasks"}


async def hub_phase(ctx: dict[str, Any]) -> dict[str, Any]:
    if consume_skip_hub_flag() and not ctx.get("skip_hub_calls"):
        ctx["skip_hub_calls"] = True
        ctx["hub_skip_reason"] = "autopoiesis_degraded"

    if ctx.get("skip_hub_calls"):
        ctx["hub_hit"] = {"reason": "idle_skip"}
        ctx["active_task"] = None
        ctx["hub_lessons"] = []
        return ctx

    signals = ctx.get("signals", [])
    try:
        result = await fetch_tasks(limit=5, signals=signals)
    except Exception as exc:
        result = {"ok": False, "error": str(exc), "tasks": []}

    if not result.get("ok"):
        ctx["hub_hit"] = {"reason": "offline", "error": result.get("error")}
        ctx["active_task"] = None
        ctx["hub_lessons"] = []
        _apply_hub_payload(ctx, result)
        ctx["last_hub_fetch_ms"] = int(time.time() * 1000)
        return ctx

    _apply_hub_payload(ctx, result)
    tasks = result.get("tasks", [])
    if tasks:
        ctx["hub_hit"] = {"reason": "tasks_found", "count": len(tasks)}
        ctx["active_task"] = tasks[0]
        ctx["hub_lessons"] = [t.get("body", "") for t in tasks[:3]]
    else:
        ctx["hub_hit"] = {"reason": "no_tasks"}
        ctx["active_task"] = None
        ctx["hub_lessons"] = []

    ctx["last_hub_fetch_ms"] = int(time.time() * 1000)
    return ctx
