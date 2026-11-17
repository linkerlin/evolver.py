"""Dispatch phase: emit prompt / sessions_spawn / solidify state.

Equivalent to evolver/src/evolve/pipeline/dispatch.js.
"""

from __future__ import annotations

import json
from typing import Any

from evolver import config as config_mod
from evolver.gep.bridge import render_sessions_spawn_call, write_prompt_artifact
from evolver.gep.feature_flags import is_enabled
from evolver.gep.memory_bridge import serialize_memory_advice
from evolver.gep.multi_proposer import (
    MultiProposerRequest,
    build_multi_proposer_prompt,
)
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
        # Self-Harness C-1: cross-process ref for the solidify acceptance gate
        # (B1 causal artifact persisted by diagnosis_phase).
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
        # Charter §5.4: WHICH library snapshot the candidate consulted this
        # cycle — the comparison must show active still pointing at Parent
        # while this id was read.
        "library_snapshot": ctx.get("library_active_id"),
        # P4-a reuse attribution surface (created_at correlates same-cycle).
        "created_at": utc_now_iso(),
        "source_type": source_type,
        "reused_asset_id": reused_asset_id,
        "reused_chain_id": reused_chain_id,
    }
    write_state_for_solidify(last_run)


def _format_preview(items: list[dict[str, Any]]) -> str:
    return "```json\n" + json.dumps(items, indent=2, ensure_ascii=False) + "\n```"


def _build_operator_cards_block(ctx: dict[str, Any], gene: dict[str, Any] | None) -> str:
    try:
        from evolver.gep.index_db import query_operator_stats
        from evolver.gep.operator_cards import (
            _load_seen_cards_from_state,
            _save_seen_cards_to_state,
            dedupe_seen_cards,
            render_operator_card,
        )

        genes = [g for g in (ctx.get("genes") or []) if isinstance(g, dict) and g.get("id")]
        candidates: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        if isinstance(gene, dict) and gene.get("id"):
            candidates.append(gene)
            seen_ids.add(str(gene["id"]))
        for g in genes:
            gid = str(g["id"])
            if gid not in seen_ids and (g.get("lens") is not None or len(candidates) < 3):
                candidates.append(g)
                seen_ids.add(gid)
            if len(candidates) >= 3:
                break
        if not candidates:
            return ""
        stats_rows = {
            str(r.get("gene_id") or ""): r
            for r in query_operator_stats(limit=50, auto_sync=False)
            if r.get("gene_id")
        }
        cards_map = {
            str(g["id"]): render_operator_card(g, stats_rows.get(str(g["id"]))) for g in candidates
        }
        rendered, updated = dedupe_seen_cards(cards_map, _load_seen_cards_from_state())
        _save_seen_cards_to_state(updated)
        return rendered
    except Exception:
        return ""


def _build_inspiration_block(ctx: dict[str, Any]) -> str:
    items = ctx.get("inspiration_operators") or []
    if not isinstance(items, list) or not items:
        return ""
    lines = []
    for item in items[:2]:
        if isinstance(item, dict) and item.get("id"):
            lines.append(
                f"- `{item['id']}` (family={item.get('family', 'general')}): "
                f"{str(item.get('summary') or '')[:100]}"
            )
    return "\n".join(lines)


def _build_structure_mirror_line() -> str:
    try:
        from evolver.gep.blackbox import render_mutation_structure_mirror

        return render_mutation_structure_mirror()
    except Exception:
        return ""


def _format_hub_matched_block(hub_hit: Any) -> str:
    """Sanitize Hub status for GEP prompts; omit noisy offline/404 failure blobs."""
    if not isinstance(hub_hit, dict) or not hub_hit:
        return ""
    if hub_hit.get("reason") in (
        "offline",
        "hub_endpoint_missing",
        "idle_skip",
        "no_tasks",
    ) and not hub_hit.get("id"):
        return ""
    sanitized = {k: v for k, v in hub_hit.items() if k != "error"}
    return json.dumps(sanitized, ensure_ascii=False) if sanitized else ""


async def dispatch_phase(ctx: dict[str, Any]) -> dict[str, Any]:
    _write_solidify_state(ctx)

    if is_enabled("enable_idle_scheduler"):
        import os

        from evolver.config import get_config

        override = os.environ.get("IDLE_OVERRIDE", "").strip().lower()
        enforce = get_config().enforce_idle_scheduler
        intensity = str(ctx.get("evolution_intensity") or "")
        if override == "signal_only" or (enforce and intensity == "signal_only"):
            ctx["skip_mutation_signal_only"] = True
            print("Signal-only intensity active; skipping mutation dispatch.")
            return ctx

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

    parent_event_id = ctx.get("parent_event_id")

    context_parts = [
        ctx.get("mutation_directive", ""),
        ctx.get("health_report", ""),
        ctx.get("recall_section", ""),
        ctx.get("autopoiesis_context", ""),
        ctx.get("causal_cluster_brief", ""),  # Self-Harness B2
        ctx.get("proposer_surface_block", ""),  # Self-Harness A2
        ctx.get("constrained_hook_block", ""),  # Self-Harness C1
        ctx.get("library_block", ""),  # Charter §5.4 in-cycle consultation
    ]

    # RSI P1-4: failure-side evidence pack — what THIS signal family already
    # tried, outcomes, rejection reasons, and duplicate-edit fingerprints.
    # Read-only over the event lineage; novel families render empty (no
    # section). Budget is a module constant, not an env knob.
    evidence_pack_block = ""
    try:
        from evolver.gep.evidence_pack import build_evidence_pack, render_evidence_pack

        pack_events = ctx.get("recent_events")
        if not isinstance(pack_events, list) or not pack_events:
            from evolver.gep.asset_store import read_all_events

            pack_events = read_all_events()[-50:]
        pack = build_evidence_pack(pack_events, ctx.get("signals", []))
        evidence_pack_block = render_evidence_pack(pack)
        ctx["evidence_pack"] = pack
    except Exception as exc:  # prompt assembly must never abort dispatch
        ctx["evidence_pack_error"] = str(exc)

    # 经验即证据 §5.2: the previous round's record precedes the evidence pack
    # — record-side evidence before result-side scores. Read-only over the
    # episode store; the writer lives at the cycle boundary (pinned).
    episode_block = ""
    try:
        from evolver.gep import episode_record

        entries = episode_record.list_episodes()
        if entries and isinstance(entries[-1], dict):
            latest_id = str(entries[-1].get("id") or "")
            body = episode_record.load_episode(latest_id) if latest_id else None
            prev_body: dict[str, Any] | None = None
            if len(entries) >= 2 and isinstance(entries[-2], dict):
                prev_id = str(entries[-2].get("id") or "")
                prev_body = episode_record.load_episode(prev_id) if prev_id else None
            if body is not None:
                episode_block = episode_record.render_episode_block(body, ep_id=latest_id)
                # After the shared summary, not inside it: a perfect-baseline
                # tie is not a refutation, and the ablation arm must not see
                # this sentence.
                note = episode_record.ceiling_tie_note(body)
                if note:
                    episode_block = f"{episode_block}\n{note}"
                attr_note = episode_record.attribution_note(body)
                if attr_note and "- attribution:" not in episode_block:
                    episode_block = f"{episode_block}\n{attr_note}"
                contrast_note = episode_record.behavioral_contrast_note(body, prev_body)
                if contrast_note and "- behavioral_contrast:" not in episode_block:
                    episode_block = f"{episode_block}\n{contrast_note}"
                ctx["episode_block"] = body
    except Exception as exc:  # prompt assembly must never abort dispatch
        ctx["episode_block_error"] = str(exc)

    # The clue layer: host-reported material, separately tagged, weakest last.
    clue_block = ""
    try:
        from evolver.gep import episode_clue, working_memory

        clues = episode_clue.recent_clues()
        working_clue = working_memory.render_working_clue()
        if clues or working_clue:
            clue_block = episode_clue.render_clue_block(clues)
            if working_clue:
                clue_block = f"{clue_block}\n{working_clue}"
        if clues:
            ctx["clue_block"] = clues
    except Exception as exc:  # prompt assembly must never abort dispatch
        ctx["clue_block_error"] = str(exc)

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
        hub_matched_block=_format_hub_matched_block(ctx.get("hub_hit")),
        cycle_id=ctx.get("cycle_id", "0000"),
        recent_history="",
        failed_capsules=ctx.get("recent_failed_capsules", []),
        hub_lessons=ctx.get("hub_lessons", []),
        strategy_policy=ctx.get("strategy_policy"),
        initial_user_prompt=ctx.get("initial_user_prompt"),
        evidence_pack=evidence_pack_block,
        episode_block=episode_block,
        clue_block=clue_block,
        operator_cards_block=_build_operator_cards_block(ctx, gene),
        adjacent_inspiration_block=_build_inspiration_block(ctx),
        structure_mirror_line=_build_structure_mirror_line(),
    )

    # Expose the assembled prompt to in-process callers (MCP swarm_tick) so the
    # host-agent executor can consume it structurally instead of parsing stdout.
    # 配对会话 §5.2 — last line of defence. Whatever earlier stages assembled,
    # the sealed val split must not leave this function in executor-facing
    # text. Counted redaction, never a silent rewrite.
    try:
        from evolver.gep.val_seal import redact

        prompt, dispatch_seal = redact(prompt, where="dispatch")
        if dispatch_seal.get("redacted"):
            ctx["dispatch_seal"] = dispatch_seal
            ctx["dispatch_seal_redacted"] = int(dispatch_seal["redacted"])
    except Exception as exc:  # dispatch must still produce a prompt
        ctx["dispatch_seal_error"] = str(exc)

    ctx["dispatch_prompt"] = prompt

    # The artifact feeds swarm_status + the evolver://dispatch/last resource —
    # it must track the LATEST dispatch regardless of how the cycle was run
    # (round-11: bash-mediated ticks left the resource hours stale because the
    # write was gated on bridge_enabled, which needs OPENCLAW_WORKSPACE).
    write_prompt_artifact(prompt)

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
        print("BUILT_PROMPT")
        print(prompt)
        print("\nSOLIDIFY REQUIRED")

    return ctx


async def dispatch_multi_propose_phase(ctx: dict[str, Any]) -> dict[str, Any]:
    """Self-Harness C2: emit a mechanism-diverse multi-proposal prompt.

    Activated when ``MULTI_PROPOSE_ROUTES > 1``. Prints the strict
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
