"""Dispatch phase: emit prompt / sessions_spawn / solidify state.

Equivalent to evolver/src/evolve/pipeline/dispatch.js.
"""

from __future__ import annotations

import json
from typing import Any

from evolver.gep.bridge import render_sessions_spawn_call, write_prompt_artifact
from evolver.gep.prompt import build_gep_prompt
from evolver.gep.memory_bridge import serialize_memory_advice
from evolver.gep.solidify import write_state_for_solidify


def _write_solidify_state(ctx: dict[str, Any]) -> None:
    last_run = {
        "run_id": ctx.get("run_id"),
        "signals": ctx.get("signals", []),
        "selected_gene_id": ctx.get("selected_gene", {}).get("id")
        if ctx.get("selected_gene")
        else None,
        "selected_capsule_id": ctx.get("selected_capsule_id"),
        "mutation": ctx.get("mutation"),
        "personality_state": ctx.get("personality_state"),
        "parent_event_id": ctx.get("parent_event_id"),
        "failure_diagnosis": ctx.get("failure_diagnosis"),
        "hub_quality_gate": ctx.get("hub_quality_gate"),
        "hub_hit": ctx.get("hub_hit"),
        "hub_response": ctx.get("hub_response"),
        "hub_service_hits": ctx.get("hub_service_hits"),
        "hub_assets": ctx.get("hub_assets"),
        "autopoiesis": ctx.get("autopoiesis"),
        "memory_advice": serialize_memory_advice(ctx.get("memory_advice")),
        "memory_graph_friction_synced": ctx.get("memory_graph_friction_synced"),
        "innovation_attempt_id": ctx.get("innovation_attempt_id"),
    }
    write_state_for_solidify(last_run)


def _format_preview(items: list[dict[str, Any]]) -> str:
    return "```json\n" + json.dumps(items, indent=2, ensure_ascii=False) + "\n```"


async def dispatch_phase(ctx: dict[str, Any]) -> dict[str, Any]:
    _write_solidify_state(ctx)

    if ctx.get("skip_hub_calls"):
        print("Idle cycle complete.")
        return ctx

    gene = ctx.get("selected_gene")
    if not gene:
        print("No matching Gene found; nothing to dispatch.")
        return ctx

    genes_preview = _format_preview(ctx.get("genes", [])[:10])
    capsules_preview = _format_preview(ctx.get("capsules", [])[:10])

    context_parts = [
        ctx.get("mutation_directive", ""),
        ctx.get("health_report", ""),
        ctx.get("recall_section", ""),
        ctx.get("autopoiesis_context", ""),
    ]
    prompt = build_gep_prompt(
        now_iso=ctx.get("scan_time_iso", ""),
        context="\n".join(part for part in context_parts if part),
        signals=ctx.get("signals", []),
        selector={"selectedBy": ctx.get("selected_by", "score_ranked")},
        parent_event_id=ctx.get("parent_event_id"),
        selected_gene=gene,
        capsule_candidates="(none)",
        genes_preview=genes_preview,
        capsules_preview=capsules_preview,
        capability_candidates_preview=ctx.get("capability_candidates_preview", "(none)"),
        external_candidates_preview=ctx.get("external_candidates_preview", "(none)"),
        hub_matched_block=json.dumps(ctx.get("hub_hit", {}), ensure_ascii=False),
        cycle_id=ctx.get("cycle_id", "0000"),
        recent_history="",
        failed_capsules=ctx.get("recent_failed_capsules", []),
        hub_lessons=ctx.get("hub_lessons", []),
        strategy_policy=ctx.get("strategy_policy"),
        initial_user_prompt=ctx.get("initial_user_prompt"),
    )

    if ctx.get("bridge_enabled"):
        artifact_path = write_prompt_artifact(prompt)
        spawn = render_sessions_spawn_call(
            {
                "task": prompt[:4000],
                "agentId": ctx.get("AGENT_NAME", "main"),
                "label": f"gep_{ctx.get('cycle_id', '0000')}",
                "cleanup": "delete",
            }
        )
        print(spawn)
    else:
        print("BUILT_PROMPT")
        print(prompt)
        print("\nSOLIDIFY REQUIRED")

    return ctx
