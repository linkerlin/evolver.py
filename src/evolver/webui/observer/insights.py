"""Pipeline insights for WebUI — failure diagnosis, hub quality gate, autopoiesis."""

from __future__ import annotations

import time
from typing import Any

from evolver.evolve.pipeline.collect import diagnose_session_log, read_real_session_log
from evolver.gep.asset_store import read_json_if_exists
from evolver.gep.autopoiesis import read_latest_tick, read_preflight_abort_report
from evolver.gep.hub_gate import enrich_hub_quality
from evolver.gep.memory_bridge import build_memory_sync_summary
from evolver.gep.paths import get_solidify_state_path


def _live_failure_diagnosis() -> dict[str, Any] | None:
    return diagnose_session_log(read_real_session_log())


def _hub_gate_from_run(last_run: dict[str, Any]) -> dict[str, Any]:
    if last_run.get("hub_quality_gate"):
        return last_run["hub_quality_gate"]
    if not (
        last_run.get("hub_service_hits")
        or last_run.get("hub_assets")
        or last_run.get("hub_response")
    ):
        return {"services": [], "assets": []}
    try:
        return enrich_hub_quality(
            {
                "hub_response": last_run.get("hub_response"),
                "hub_service_hits": last_run.get("hub_service_hits"),
                "hub_assets": last_run.get("hub_assets"),
            }
        )
    except Exception:
        return {"services": [], "assets": []}


def pipeline_insights() -> dict[str, Any]:
    """Aggregate failure diagnosis and hub quality data for the dashboard."""
    state = read_json_if_exists(get_solidify_state_path()) or {}
    last_run = state.get("last_run") if isinstance(state.get("last_run"), dict) else {}

    diagnosis = last_run.get("failure_diagnosis")
    diagnosis_source = "last_run" if diagnosis else "session_log"
    if not diagnosis:
        diagnosis = _live_failure_diagnosis()

    hub_gate = _hub_gate_from_run(last_run)
    service_count = len(hub_gate.get("services") or [])
    asset_count = len(hub_gate.get("assets") or [])

    autopoiesis = last_run.get("autopoiesis")
    autopoiesis_source = "last_run" if autopoiesis else None
    if not autopoiesis:
        tick = read_latest_tick()
        if tick:
            autopoiesis = {
                "self_report": tick.get("self_report"),
                "viability": tick.get("viability"),
                "homeostasis": tick.get("homeostasis"),
                "tick_id": tick.get("id"),
            }
            autopoiesis_source = "log"

    preflight_abort = read_preflight_abort_report()
    innovation_summary: dict[str, Any] | None = None
    try:
        from evolver.ops.innovation import get_innovation_summary

        innovation_summary = get_innovation_summary()
    except Exception:
        pass

    memory_sync = build_memory_sync_summary(last_run=last_run)

    return {
        "timestamp": time.time(),
        "run_id": last_run.get("run_id"),
        "pending_solidify": bool(last_run) and not state.get("last_solidify"),
        "preflight_abort": preflight_abort,
        "innovation_summary": innovation_summary,
        "memory_sync": memory_sync,
        "hub_hit": last_run.get("hub_hit"),
        "failure_diagnosis": diagnosis,
        "failure_diagnosis_source": diagnosis_source if diagnosis else None,
        "hub_quality_gate": hub_gate,
        "hub_quality_summary": {
            "service_reviews": service_count,
            "asset_checks": asset_count,
            "has_data": service_count > 0 or asset_count > 0,
        },
        "autopoiesis": autopoiesis,
        "autopoiesis_source": autopoiesis_source,
    }
