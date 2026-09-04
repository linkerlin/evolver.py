"""Dispatch phase: emit prompt / sessions_spawn / solidify state.

Equivalent to evolver/src/evolve/pipeline/dispatch.js.
"""

from __future__ import annotations

import json
from typing import Any

from evolver import config as config_mod
from evolver.gep.asset_store import get_last_event_id
from evolver.gep.bridge import render_sessions_spawn_call, write_prompt_artifact
from evolver.gep.feature_flags import is_enabled
from evolver.gep.hooks.taxonomy import (
    hook_belongs_to_family,
    hooks_for_family,
    known_family,
)
from evolver.gep.memory_bridge import serialize_memory_advice
from evolver.gep.multi_proposer import (
    MultiProposerRequest,
    build_multi_proposer_prompt,
)
from evolver.gep.paths import get_gep_assets_dir, get_workspace_root
from evolver.gep.prompt import build_gep_prompt
from evolver.gep.reuse_attribution import utc_now_iso
from evolver.gep.solidify import write_state_for_solidify
from evolver.gep.surface import (
    capture_surface,
    load_snapshot,
    render_surface_block,
    save_snapshot,
    surface_delta,
)


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
        # Self-Harness C-1: cross-process ref for the solidify acceptance gate
        # (B1 causal artifact persisted by diagnosis_phase).
        "diagnosis_ref": ctx.get("causal_analyses_ref"),
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


def _anchor_proposer_surface(ctx: dict[str, Any]) -> None:
    """Self-Harness A2: anchor the proposer to a stable baseline surface.

    Opt-in via ``enable_surface_decouple`` + ``ctx["surface_files"]`` (list of
    relative paths). The baseline snapshot is loaded from disk when present
    (stable across cycles); otherwise captured now and persisted. The rendered
    block (baseline id + eval drift) feeds the GEP prompt via
    ``ctx["proposer_surface_block"]``.
    """
    if not is_enabled("enable_surface_decouple"):
        return
    surface_files = ctx.get("surface_files")
    if not isinstance(surface_files, list) or not surface_files:
        return

    root = get_workspace_root()
    paths = [root / rel for rel in surface_files]
    baseline_path = get_gep_assets_dir() / "surfaces" / "baseline.json"

    baseline = load_snapshot(baseline_path)
    if baseline is None:
        baseline = capture_surface(paths, root=root)
        save_snapshot(baseline, baseline_path)

    eval_snap = capture_surface(paths, root=root)
    delta = surface_delta(baseline, eval_snap)
    ctx["proposer_surface_snapshot"] = baseline.model_dump()
    ctx["proposer_surface_block"] = render_surface_block(baseline, delta)


def _anchor_constrained_hook(ctx: dict[str, Any]) -> None:
    """Self-Harness C1: constrain the proposer to a closed hook vocabulary.

    Opt-in via ``enable_constrained_genes``. When the selected gene declares
    ``mechanism_family`` + ``target_hook``, a constraint block is injected
    telling the proposer it may ONLY edit that hook within that family.
    """
    if not is_enabled("enable_constrained_genes"):
        return
    gene = ctx.get("selected_gene")
    if not isinstance(gene, dict):
        return
    family = gene.get("mechanism_family")
    hook = gene.get("target_hook")
    if not isinstance(family, str) or not family:
        return
    if not isinstance(hook, str) or not hook:
        return
    if not known_family(family):
        return
    if not hook_belongs_to_family(family, hook):
        return
    allowed = ", ".join(hooks_for_family(family))
    ctx["constrained_hook_block"] = (
        "# CONSTRAINED EDIT MODE (closed vocabulary — safety enforced)\n"
        f"- mechanism_family: {family}\n"
        f"- target_hook: {hook} (the ONLY editable hook)\n"
        f"- family hooks: {allowed}\n"
        "- Do NOT propose changes to any other hook or file."
    )


def _format_preview(items: list[dict[str, Any]]) -> str:
    return "```json\n" + json.dumps(items, indent=2, ensure_ascii=False) + "\n```"


def _build_lineage_lessons(
    gene_id: str,
    events: list[dict[str, Any]],
    *,
    limit: int = 3,
) -> str:
    """Sprint 22.6 (GEPA ancestry): the selected gene's recent failures,
    compacted into prompt lessons so candidates inherit their lineage's
    learning signals instead of rediscovering them."""
    if not gene_id or not events:
        return ""
    lessons: list[str] = []
    for evt in reversed(events):  # newest first
        if evt.get("gene_id") != gene_id:
            continue
        outcome = evt.get("outcome") or {}
        if outcome.get("status") != "failed":
            continue
        reason = (
            outcome.get("error") or (evt.get("acceptance_result") or {}).get("reason") or "unknown"
        )
        br = evt.get("blast_radius") or {}
        signals = ", ".join(str(s) for s in (evt.get("signals") or [])[:3])
        category = (evt.get("mutation") or {}).get("category") or "?"
        lessons.append(
            f"- [{category}] {reason} "
            f"(blast {br.get('files', '?')}f/{br.get('lines', '?')}l; signals: {signals})"
        )
        if len(lessons) >= limit:
            break
    if not lessons:
        return ""
    header = "## Lineage Lessons (GEPA ancestry)"
    return f"{header}\nGene `{gene_id}` failed before with:\n" + "\n".join(lessons)


async def dispatch_phase(ctx: dict[str, Any]) -> dict[str, Any]:
    _write_solidify_state(ctx)
    _anchor_proposer_surface(ctx)
    _anchor_constrained_hook(ctx)

    if ctx.get("skip_hub_calls"):
        # Saturation steady-state (no hub_skip_reason) is an intentional pause.
        # Degraded modes (hub offline flag / preflight-abort recovery) skip Hub
        # ENRICHMENT, not local evolution — dispatching the selected gene here
        # removes the burn-a-whole-tick latency a degraded cycle used to add
        # (dogfood round-3: fresh signals needed two ticks to dispatch).
        if ctx.get("hub_skip_reason") not in ("autopoiesis_degraded", "preflight_abort_recovery"):
            print("Idle cycle complete.")
            return ctx
        print("Degraded cycle: dispatching local gene without Hub enrichment.")

    gene = ctx.get("selected_gene")
    if not gene:
        print("No matching Gene found; nothing to dispatch.")
        return ctx

    genes_preview = _format_preview(ctx.get("genes", [])[:10])
    capsules_preview = _format_preview(ctx.get("capsules", [])[:10])

    # Sprint 22.6 (enable_lineage_lessons, GEPA ancestry): fill the prompt's
    # existing parent_event_id slot and inject the selected gene's failure
    # lineage as lessons.
    parent_event_id = ctx.get("parent_event_id")
    lineage_block = ""
    if is_enabled("enable_lineage_lessons"):
        if parent_event_id is None:
            parent_event_id = get_last_event_id()
        lineage_block = _build_lineage_lessons(
            str(gene.get("id") or ""),
            ctx.get("recent_events") or [],
        )

    context_parts = [
        ctx.get("mutation_directive", ""),
        ctx.get("health_report", ""),
        ctx.get("recall_section", ""),
        ctx.get("autopoiesis_context", ""),
        ctx.get("causal_cluster_brief", ""),  # Self-Harness B2
        ctx.get("proposer_surface_block", ""),  # Self-Harness A2
        ctx.get("constrained_hook_block", ""),  # Self-Harness C1
        lineage_block,  # Sprint 22.6
    ]
    prompt = build_gep_prompt(
        now_iso=ctx.get("scan_time_iso", ""),
        context="\n".join(part for part in context_parts if part),
        signals=ctx.get("signals", []),
        selector={"selectedBy": ctx.get("selected_by", "score_ranked")},
        parent_event_id=parent_event_id,
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

    # Expose the assembled prompt to in-process callers (MCP swarm_tick) so the
    # host-agent executor can consume it structurally instead of parsing stdout.
    ctx["dispatch_prompt"] = prompt

    if ctx.get("bridge_enabled"):
        write_prompt_artifact(prompt)
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


async def dispatch_multi_propose_phase(ctx: dict[str, Any]) -> dict[str, Any]:
    """Self-Harness C2: emit a mechanism-diverse multi-proposal prompt.

    Activated when ``EVOLVER_MULTI_PROPOSE_ROUTES > 1``. Prints the strict
    multi-slot contract (N distinct mechanisms, decline allowed) instead of
    the single GEP prompt; the external proposer responds with N proposals.
    """
    routes = config_mod.MULTI_PROPOSE_ROUTES
    if routes <= 1:
        return ctx

    context_parts = [
        ctx.get("mutation_directive", ""),
        ctx.get("health_report", ""),
        ctx.get("recall_section", ""),
        ctx.get("autopoiesis_context", ""),
        ctx.get("causal_cluster_brief", ""),  # Self-Harness B2
    ]
    request = MultiProposerRequest(
        diagnosis_brief=ctx.get("causal_brief", ""),
        causal_clusters_brief=ctx.get("causal_cluster_brief", ""),
        route_count=routes,
        strict_noop=True,
        extra_context="\n".join(part for part in context_parts if part),
    )
    prompt = build_multi_proposer_prompt(request)
    if ctx.get("bridge_enabled"):
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
        print("BUILT_MULTI_PROPOSE_PROMPT")
        print(prompt)
        print("\nMULTI PROPOSE REQUIRED")
    return ctx
