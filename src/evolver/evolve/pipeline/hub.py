"""Hub phase: coordinate with EvoMap Hub / local Proxy.

Equivalent to evolver/src/evolve/pipeline/hub.js.
"""

from __future__ import annotations

import time
from typing import Any

from evolver.gep.a2a_protocol import fetch_tasks


async def hub_phase(ctx: dict[str, Any]) -> dict[str, Any]:
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
        ctx["last_hub_fetch_ms"] = int(time.time() * 1000)
        return ctx

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
