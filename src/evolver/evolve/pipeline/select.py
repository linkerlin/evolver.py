"""Select phase: choose Gene / Capsule and build mutation.

Equivalent to evolver/src/evolve/pipeline/select.js.
"""

from __future__ import annotations

import contextlib
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
    policy = {
        "policy": strategy.name,
        "repair": strategy.repair,
        "optimize": strategy.optimize,
        "innovate": strategy.innovate,
        "force_innovation": ctx.get("IS_RANDOM_DRIFT", False),
    }
    # EvoX adaptive-mutation-rate harvest: the unified feedback channel shifts
    # the weights (degraded streak → repair bias; converged plateau → novelty).
    # Neutral no-op without a feedback journal (CLI/daemon users unaffected).
    from evolver.config import ADAPTIVE_MUTATION_ENABLED

    if ADAPTIVE_MUTATION_ENABLED:
        with contextlib.suppress(Exception):
            from evolver.gep.adaptive import apply_adaptive_bias, feedback_mutation_bias
            from evolver.gep.feedback import load_recent_feedback

            policy = apply_adaptive_bias(policy, feedback_mutation_bias(load_recent_feedback(10)))
    return policy


async def select_phase(ctx: dict[str, Any]) -> dict[str, Any]:
    policy = compute_adaptive_strategy_policy(ctx)
    signals = list(ctx.get("signals", []))
    from evolver.gep.feedback import FEEDBACK_SIGNAL_DEGRADED

    adaptive_mode = ""
    adaptive = policy.get("adaptive")
    if isinstance(adaptive, dict):
        adaptive_mode = str(adaptive.get("mode") or "")
    if FEEDBACK_SIGNAL_DEGRADED in {str(s) for s in signals} or adaptive_mode == "repair_bias":
        ctx["autopoiesis_repair_bias"] = True
    genes = ctx.get("genes", [])
    capsules = ctx.get("capsules", [])
    memory_advice = dict(ctx.get("memory_advice") or {})

    # Harness2 closed-loop guard: if the immediately preceding episode hurt
    # validation checks, pivot to repair mode and cool down the offending gene
    # when alternative genes are available.
    with contextlib.suppress(Exception):
        from evolver.gep import episode_record

        ep_entries = episode_record.list_episodes()
        if ep_entries and isinstance(ep_entries[-1], dict):
            latest_ep_id = str(ep_entries[-1].get("id") or "")
            latest_ep = episode_record.load_episode(latest_ep_id) if latest_ep_id else None
            if isinstance(latest_ep, dict):
                raw_gates = latest_ep.get("gates")
                gates: dict[str, Any] = raw_gates if isinstance(raw_gates, dict) else {}
                raw_gene = latest_ep.get("gene")
                gene_obj: dict[str, Any] = raw_gene if isinstance(raw_gene, dict) else {}
                raw_checks = latest_ep.get("checks")
                checks_list: list[dict[str, Any]] = (
                    [c for c in raw_checks if isinstance(c, dict)]
                    if isinstance(raw_checks, list)
                    else []
                )
                raw_outcome = latest_ep.get("outcome")
                outcome_dict: dict[str, Any] | None = (
                    raw_outcome if isinstance(raw_outcome, dict) else None
                )
                raw_pred = gates.get("prediction_delta")
                pred_dict: dict[str, Any] | None = raw_pred if isinstance(raw_pred, dict) else None
                attr = gates.get("attribution") or latest_ep.get("attribution")
                if not isinstance(attr, dict):
                    attr = episode_record.compute_component_attribution(
                        str(latest_ep.get("diff") or ""),
                        checks_list,
                        outcome=outcome_dict,
                        prediction_delta=pred_dict,
                        target_hook=str(gene_obj.get("target_hook") or "") or None,
                    )
                attr_status = (
                    (attr.get("status") or attr.get("outcome")) if isinstance(attr, dict) else None
                )
                if attr_status == "hurt":
                    ctx["autopoiesis_repair_bias"] = True
                    hurt_gene = str(gene_obj.get("id") or latest_ep.get("gene_id") or "").strip()
                    if hurt_gene:
                        ctx["previous_episode_hurt_gene_id"] = hurt_gene
                        if isinstance(genes, list) and len(genes) > 1:
                            banned = set(memory_advice.get("bannedGeneIds") or set())
                            banned.add(hurt_gene)
                            memory_advice["bannedGeneIds"] = banned

    if ctx.get("autopoiesis_repair_bias"):
        policy = {**policy, "repair": True, "optimize": False, "innovate": False}
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
            "recentEvents": recent_events,
        }
    )

    selected_gene = selection.get("selectedGene")
    selected_capsule = selection.get("selectedCapsule")

    # Record hypothesis/attempt
    with contextlib.suppress(Exception):
        record_hypothesis(
            signals=signals,
            selected_gene=selected_gene,
            drift_enabled=drift_enabled,
            run_id=ctx.get("run_id"),
        )

    with contextlib.suppress(Exception):
        record_attempt(
            signals=signals,
            selected_gene=selected_gene,
            drift_enabled=drift_enabled,
            run_id=ctx.get("run_id"),
        )

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
