"""Enrich phase: augment context with memory advice, hub hits, observations.

Equivalent to evolver/src/evolve/pipeline/enrich.js.
"""

from __future__ import annotations

from typing import Any

from evolver.gep.asset_store import read_recent_failed_capsules
from evolver.gep.cognition import enrich_cycle_context
from evolver.gep.hub_gate import enrich_hub_quality
from evolver.gep.memory_bridge import bidirectional_memory_sync
from evolver.gep.memory_graph import get_memory_advice, record_signal_snapshot


async def enrich_phase(ctx: dict[str, Any]) -> dict[str, Any]:
    signals = ctx.get("signals", [])
    genes = ctx.get("genes", [])

    # Record signal snapshot
    try:
        record_signal_snapshot(signals=signals, run_id=ctx.get("run_id"))
    except Exception:
        pass

    ctx["observations"] = {
        "signals_count": len(signals),
        "genes_count": len(genes),
        "capsules_count": len(ctx.get("capsules", [])),
    }

    # Real memory advice from memory graph
    try:
        advice = get_memory_advice(
            signals=signals,
            genes=genes,
            drift_enabled=bool(ctx.get("IS_RANDOM_DRIFT", False)),
        )
    except Exception:
        advice = {
            "currentSignalKey": "",
            "preferredGeneId": None,
            "bannedGeneIds": set(),
            "explanation": "memory advice unavailable",
            "totalAttempts": 0,
        }
    sync = bidirectional_memory_sync(
        living_memory=ctx.get("living_memory"),
        advice=advice,
        signals=list(signals),
        run_id=ctx.get("run_id"),
    )
    ctx["memory_advice"] = sync["memory_advice"]
    if sync["signals_added"]:
        ctx["signals"] = sync["signals"]
        ctx["living_memory_signals_merged"] = sync["signals_added"]
    if sync["living_memory_graph_sync"].get("synced"):
        ctx["memory_graph_friction_synced"] = sync["living_memory_graph_sync"]

    # Recent failed capsules
    try:
        ctx["recent_failed_capsules"] = read_recent_failed_capsules(limit=20)
    except Exception:
        ctx["recent_failed_capsules"] = []

    # Capability candidates (Sprint 15.5) — problem:*/action:* expansion + candidates
    try:
        from evolver.gep.candidates import (  # noqa: PLC0415
            expand_signals,
            extract_capability_candidates,
            render_candidates_preview,
        )

        signal_names = [
            str(s.get("type") if isinstance(s, dict) else s)
            for s in (ctx.get("signals") or [])
            if s
        ]
        ctx["expanded_signals"] = expand_signals(signal_names, "")
        caps = extract_capability_candidates(
            {
                "signals": signal_names,
                "recent_failed_capsules": ctx.get("recent_failed_capsules") or [],
                "recent_session_transcript": ctx.get("recent_session_transcript") or "",
            }
        )
        ctx["capability_candidates"] = caps
        ctx["capability_candidates_preview"] = render_candidates_preview(caps) if caps else "(none)"
    except Exception:
        ctx.setdefault("capability_candidates", [])
        ctx.setdefault("capability_candidates_preview", "(none)")

    # Plateau detection
    ctx["plateau_override"] = {"severity": None}
    if any(s.startswith("plateau_pivot_required") for s in signals):
        ctx["IS_RANDOM_DRIFT"] = True
        ctx["plateau_override"] = {"severity": "required"}
    elif any(s.startswith("plateau_pivot_suggested") for s in signals):
        ctx["plateau_override"] = {"severity": "suggested"}

    if ctx.get("hub_service_hits") or ctx.get("hub_assets") or ctx.get("hub_response"):
        try:
            ctx["hub_quality_gate"] = enrich_hub_quality(ctx)
        except Exception:
            ctx["hub_quality_gate"] = {"services": [], "assets": []}

    enrich_cycle_context(ctx)
    return ctx
