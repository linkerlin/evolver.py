"""Hub phase: coordinate with EvoMap Hub / local Proxy.

Equivalent to evolver/src/evolve/pipeline/hub.js.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Final

from evolver.gep.a2a_protocol import fetch_tasks
from evolver.gep.autopoiesis import consume_skip_hub_flag

#: Round-45 (phase-telemetry finding): the Hub endpoint answers 404 fast-ish
#: but with wild latency variance (3.3s .. 15.7s observed per cycle — over
#: half the MCP tick budget). 404 is an endpoint FACT, not a transient: after
#: this many consecutive 404s the phase short-circuits the fetch entirely and
#: re-probes only after the TTL. Module constants, not env knobs.
HUB_404_STICKY_THRESHOLD: Final = 3
HUB_404_REPROBE_S: Final = 24 * 3600.0


def _state_path() -> Path:
    from evolver.gep.paths import get_evolution_dir

    return get_evolution_dir() / "hub_endpoint_state.json"


def _load_state() -> dict[str, Any]:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"consecutive_404": 0, "last_probe_ts": 0.0, "skipped_cycles": 0}
    return (
        data
        if isinstance(data, dict)
        else {
            "consecutive_404": 0,
            "last_probe_ts": 0.0,
            "skipped_cycles": 0,
        }
    )


def _save_state(state: dict[str, Any]) -> None:
    try:
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass  # state persistence is best-effort; fetch behavior stays correct


def _note_404(state: dict[str, Any]) -> dict[str, Any]:
    state["consecutive_404"] = int(state.get("consecutive_404", 0)) + 1
    state["last_probe_ts"] = time.time()
    return state


def _reset_404(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("consecutive_404"):
        state["consecutive_404"] = 0
    return state


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

    # Round-45 sticky 404 short-circuit: skip ONLY the fetch. The ctx shape
    # stays identical to a failed fetch — skip_hub_calls is deliberately NOT
    # set, so dispatch behavior (local gene dispatch) is unchanged.
    state = _load_state()
    now = time.time()
    if (
        int(state.get("consecutive_404", 0)) >= HUB_404_STICKY_THRESHOLD
        and now - float(state.get("last_probe_ts", 0.0)) < HUB_404_REPROBE_S
    ):
        state["skipped_cycles"] = int(state.get("skipped_cycles", 0)) + 1
        _save_state(state)
        ctx["hub_hit"] = {
            "reason": "hub_endpoint_missing",
            "sticky": True,
            "consecutive_404": state["consecutive_404"],
            "skipped_cycles": state["skipped_cycles"],
            "next_probe_in_s": round(
                HUB_404_REPROBE_S - (now - float(state.get("last_probe_ts", 0.0)))
            ),
        }
        ctx["active_task"] = None
        ctx["hub_lessons"] = []
        return ctx

    signals = ctx.get("signals", [])
    try:
        result = await fetch_tasks(limit=5, signals=signals)
    except Exception as exc:
        result = {"ok": False, "error": str(exc), "tasks": []}

    if not result.get("ok"):
        error_text = str(result.get("error") or "")
        if "404" in error_text:
            _save_state(_note_404(state))
        else:
            # A different failure class (network/DNS) says nothing about the
            # endpoint's existence — reset honestly rather than accumulate.
            _save_state(_reset_404(state))
        ctx["hub_hit"] = {"reason": "offline", "error": result.get("error")}
        ctx["active_task"] = None
        ctx["hub_lessons"] = []
        _apply_hub_payload(ctx, result)
        ctx["last_hub_fetch_ms"] = int(time.time() * 1000)
        return ctx

    _save_state(_reset_404(state))
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
