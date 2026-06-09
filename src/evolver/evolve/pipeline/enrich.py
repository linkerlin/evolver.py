"""Enrich phase: augment context with memory advice, hub hits, observations.

Equivalent to evolver/src/evolve/pipeline/enrich.js.
"""

from __future__ import annotations

from typing import Any

from evolver.gep.memory_graph import get_memory_advice, record_signal_snapshot
from evolver.gep.asset_store import read_recent_failed_capsules


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
    ctx["memory_advice"] = advice

    # Recent failed capsules
    try:
        ctx["recent_failed_capsules"] = read_recent_failed_capsules(limit=20)
    except Exception:
        ctx["recent_failed_capsules"] = []

    # Plateau detection
    ctx["plateau_override"] = {"severity": None}
    if any(s.startswith("plateau_pivot_required") for s in signals):
        ctx["IS_RANDOM_DRIFT"] = True
        ctx["plateau_override"] = {"severity": "required"}
    elif any(s.startswith("plateau_pivot_suggested") for s in signals):
        ctx["plateau_override"] = {"severity": "suggested"}

    return ctx
