"""Dispatch phase: emit prompt / sessions_spawn / solidify state.

Equivalent to evolver/src/evolve/pipeline/dispatch.js.
"""

from __future__ import annotations

import json
from typing import Any

from evolver.gep.bridge import render_sessions_spawn_call, write_prompt_artifact
from evolver.gep.memory_bridge import serialize_memory_advice
from evolver.gep.prompt import build_gep_prompt
from evolver.gep.reuse_attribution import utc_now_iso
from evolver.gep.solidify import write_state_for_solidify


def _write_solidify_state(ctx: dict[str, Any]) -> None:
    # Derive reuse source_type for P4-a attribution (dispatch run-state).
    hub_hit = ctx.get("hub_hit")
    hub_assets = ctx.get("hub_assets") or []
    source_type = "generated"
    reused_asset_id = None
    reused_chain_id = None
    if ctx.get("selected_capsule_id") or (isinstance(hub_hit, dict) and hub_hit.get("id")):
        source_type = "reused"
        reused_asset_id = (
            ctx.get("selected_capsule_id")
            or (hub_hit.get("id") if isinstance(hub_hit, dict) else None)
            or (hub_assets[0].get("id") if hub_assets and isinstance(hub_assets[0], dict) else None)
        )
        reused_chain_id = (
            hub_hit.get("chain_id") if isinstance(hub_hit, dict) else None
        ) or ctx.get("reused_chain_id")
    elif ctx.get("external_candidates") or ctx.get("capability_candidates"):
        source_type = "reference"
        reused_asset_id = ctx.get("reused_asset_id")
        reused_chain_id = ctx.get("reused_chain_id")

    # Explicit override from enrich/select when present.
    if ctx.get("source_type") in ("reused", "reference", "generated"):
        source_type = str(ctx["source_type"])
    if ctx.get("reused_asset_id"):
        reused_asset_id = ctx.get("reused_asset_id")
    if ctx.get("reused_chain_id") is not None:
        reused_chain_id = ctx.get("reused_chain_id")

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
        # P4-a reuse attribution surface (created_at correlates same-cycle).
        "created_at": utc_now_iso(),
        "source_type": source_type,
        "reused_asset_id": reused_asset_id,
        "reused_chain_id": reused_chain_id,
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
