"""Select phase: choose Gene / Capsule and build mutation.

Equivalent to evolver/src/evolve/pipeline/select.js.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from evolver.gep.memory_graph import record_attempt, record_hypothesis
from evolver.gep.mutation import build_mutation
from evolver.gep.personality import (
    adapt_personality,
    load_personality,
    personality_to_strategy_bias,
)
from evolver.gep.selector import select_gene_and_capsule
from evolver.gep.strategy import resolve_strategy


def compute_adaptive_strategy_policy(ctx: dict[str, Any]) -> dict[str, Any]:
    strategy = resolve_strategy({"signals": ctx.get("signals", [])})
    return {
        "policy": strategy.name,
        "repair": strategy.repair,
        "optimize": strategy.optimize,
        "innovate": strategy.innovate,
        "force_innovation": ctx.get("IS_RANDOM_DRIFT", False),
    }


async def select_phase(ctx: dict[str, Any]) -> dict[str, Any]:
    policy = compute_adaptive_strategy_policy(ctx)
    if ctx.get("autopoiesis_repair_bias"):
        policy = {**policy, "repair": True, "optimize": False, "innovate": False}
    signals = list(ctx.get("signals", []))
    genes = ctx.get("genes", [])
    capsules = ctx.get("capsules", [])
    memory_advice = ctx.get("memory_advice") or {}
    drift_enabled = bool(ctx.get("IS_RANDOM_DRIFT", False))

    recent_events = ctx.get("recent_events", [])
    personality = adapt_personality(load_personality(), recent_events=recent_events)

    force_category: str | None = None
    if ctx.get("autopoiesis_repair_bias"):
        for tag in ("repair_loop", "autopoiesis:repair_loop_guard"):
            if tag not in signals:
                signals.append(tag)
        force_category = "repair"

    selection = select_gene_and_capsule(
        {
            "genes": genes,
            "capsules": capsules,
            "signals": signals,
            "memoryAdvice": memory_advice,
            "driftEnabled": drift_enabled,
        }
    )

    selected_gene = selection.get("selectedGene")
    selected_capsule = selection.get("selectedCapsule")

    # Record hypothesis/attempt
    try:
        record_hypothesis(
            signals=signals,
            selected_gene=selected_gene,
            drift_enabled=drift_enabled,
            run_id=ctx.get("run_id"),
        )
    except Exception:
        pass

    try:
        record_attempt(
            signals=signals,
            selected_gene=selected_gene,
            drift_enabled=drift_enabled,
            run_id=ctx.get("run_id"),
        )
    except Exception:
        pass

    mutation = build_mutation(
        signals=signals,
        selected_gene=selected_gene,
        drift_enabled=drift_enabled,
        personality_state=personality,
        force_category=force_category,
    )

    mutation_category = str(mutation.get("category", ""))
    if mutation_category == "innovate" or drift_enabled:
        try:
            from evolver.ops.innovation import record_innovation_attempt

            inv = record_innovation_attempt(
                gene_id=selected_gene.get("id") if selected_gene else None,
                strategy="innovate" if drift_enabled else mutation_category,
                hypothesis=ctx.get("hypothesis_id", ""),
                run_id=ctx.get("run_id"),
            )
            ctx["innovation_attempt_id"] = inv["id"]
        except Exception:
            pass

    ctx["selected_gene"] = selected_gene
    ctx["selected_capsule_id"] = selected_capsule.get("id") if selected_capsule else None
    ctx["strategy_policy"] = policy
    ctx["personality_selection"] = personality_to_strategy_bias(personality)
    ctx["personality_state"] = personality
    ctx["mutation"] = dict(mutation)
    ctx["mutation_innovate_mode"] = drift_enabled
    ctx["hypothesis_id"] = f"hyp_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
    ctx["selected_by"] = selection.get("selectionPath", "score_ranked")
    ctx["capsules_used"] = []
    return ctx
