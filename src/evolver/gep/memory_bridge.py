"""Bridge living memory ↔ memory_graph ↔ GEP pipeline signals.

Unifies Autopoiesis friction history with memory_graph advice and per-cycle
signal injection without duplicating persistence layers.
"""

from __future__ import annotations

import time
from typing import Any

MEMORY_GRAPH_BAN_PREFIX = "memory_graph_ban:"
MEMORY_GRAPH_PREFER_PREFIX = "memory_graph_prefer:"
FRICTION_CATEGORY_PREFIX = "memory_graph_friction:"


def living_memory_signal_hints(living_memory: dict[str, Any] | None) -> list[str]:
    """Derive GEP signal strings from high-friction living memory entries."""
    if not living_memory or not living_memory.get("loaded"):
        return []
    hints: list[str] = []
    for fp in living_memory.get("high_friction_points") or []:
        if not isinstance(fp, dict):
            continue
        category = str(fp.get("category") or "unknown")
        hint = f"living_memory_risk:{category}"
        if hint not in hints:
            hints.append(hint)
        rule_id = fp.get("rule_id")
        if rule_id:
            key = rule_id if str(rule_id).startswith("autopoiesis:") else f"autopoiesis:{rule_id}"
            if key not in hints:
                hints.append(key)
    return hints


def memory_graph_signal_hints(advice: dict[str, Any] | None) -> list[str]:
    """Derive GEP signal strings from memory_graph advice (bans / preferences)."""
    if not advice:
        return []
    hints: list[str] = []
    banned = advice.get("bannedGeneIds") or set()
    if not isinstance(banned, set):
        banned = set(banned)
    for gene_id in sorted(banned):
        hint = f"{MEMORY_GRAPH_BAN_PREFIX}{gene_id}"
        if hint not in hints:
            hints.append(hint)

    for field in ("solidifyPreferredGeneId", "preferredGeneId"):
        gene_id = advice.get(field)
        if gene_id:
            hint = f"{MEMORY_GRAPH_PREFER_PREFIX}{gene_id}"
            if hint not in hints:
                hints.append(hint)

    for category in advice.get("frictionCategories") or []:
        hint = f"{FRICTION_CATEGORY_PREFIX}{category}"
        if hint not in hints:
            hints.append(hint)
    return hints


def merge_unified_hints(
    living_memory: dict[str, Any] | None,
    advice: dict[str, Any] | None,
) -> list[str]:
    """Union of living-memory and memory_graph derived hints."""
    hints: list[str] = []
    for hint in living_memory_signal_hints(living_memory) + memory_graph_signal_hints(advice):
        if hint not in hints:
            hints.append(hint)
    return hints


def merge_living_memory_into_advice(
    advice: dict[str, Any],
    living_memory: dict[str, Any] | None,
) -> dict[str, Any]:
    """Augment memory_graph advice with living-memory risk hints."""
    hints = living_memory_signal_hints(living_memory)
    if not hints:
        return advice
    merged = dict(advice)
    merged["livingMemoryHints"] = hints
    explanation = str(merged.get("explanation") or "")
    merged["explanation"] = f"{explanation}; living_memory_hints={','.join(hints[:5])}".strip("; ")
    return merged


def merge_bidirectional_advice(
    advice: dict[str, Any],
    living_memory: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge living_memory and memory_graph hints into unified advice."""
    merged = merge_living_memory_into_advice(advice, living_memory)
    graph_hints = memory_graph_signal_hints(advice)
    unified = merge_unified_hints(living_memory, advice)
    if unified:
        merged["livingMemoryHints"] = unified
    if graph_hints:
        merged["memoryGraphHints"] = graph_hints
    parts: list[str] = []
    if graph_hints:
        parts.append(f"memory_graph_hints={','.join(graph_hints[:5])}")
    if unified:
        parts.append(f"unified_hints={len(unified)}")
    if parts:
        explanation = str(merged.get("explanation") or "")
        merged["explanation"] = f"{explanation}; {'; '.join(parts)}".strip("; ")
    return merged


def merge_hints_into_signals(signals: list[str], hints: list[str]) -> tuple[list[str], list[str]]:
    """Append unique hints to the signal list."""
    merged = list(signals)
    added: list[str] = []
    for hint in hints:
        if hint not in merged:
            merged.append(hint)
            added.append(hint)
    return merged, added


def sync_living_friction_to_memory_graph(
    living_memory: dict[str, Any] | None,
    *,
    signals: list[str],
    run_id: str | None = None,
) -> dict[str, Any]:
    """Push unsynced living-memory friction into memory_graph (deduped by friction id)."""
    from evolver.gep.memory_graph import (  # noqa: PLC0415
        patch_sync_state,
        read_sync_state,
        record_friction_observation,
    )

    if not living_memory or not living_memory.get("loaded"):
        return {"synced": 0, "skipped": 0, "ids": []}

    synced_map = read_sync_state().get("living_memory_friction") or {}
    if not isinstance(synced_map, dict):
        synced_map = {}

    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for bucket in ("high_friction_points", "recent_friction_points"):
        for fp in living_memory.get(bucket) or []:
            if not isinstance(fp, dict):
                continue
            fp_id = str(fp.get("id") or "")
            if not fp_id or fp_id in seen_ids:
                continue
            seen_ids.add(fp_id)
            candidates.append(fp)

    synced_ids: list[str] = []
    skipped = 0
    for fp in candidates:
        fp_id = str(fp.get("id"))
        if fp_id in synced_map:
            skipped += 1
            continue
        record_friction_observation(
            signals=signals,
            friction=fp,
            source="living_memory",
            run_id=run_id,
        )
        synced_map[fp_id] = time.time()
        synced_ids.append(fp_id)

    if synced_ids:
        patch_sync_state({"living_memory_friction": synced_map})

    return {"synced": len(synced_ids), "skipped": skipped, "ids": synced_ids}


def bidirectional_memory_sync(
    *,
    living_memory: dict[str, Any] | None,
    advice: dict[str, Any],
    signals: list[str],
    run_id: str | None = None,
) -> dict[str, Any]:
    """One-cycle living_memory ↔ memory_graph unify: advice, signals, graph writes."""
    merged_advice = merge_bidirectional_advice(advice, living_memory)
    graph_sync = sync_living_friction_to_memory_graph(
        living_memory,
        signals=signals,
        run_id=run_id,
    )
    unified_hints = list(merged_advice.get("livingMemoryHints") or [])
    merged_signals, added = merge_hints_into_signals(list(signals), unified_hints)
    return {
        "memory_advice": merged_advice,
        "signals": merged_signals,
        "signals_added": added,
        "living_memory_graph_sync": graph_sync,
    }


def capture_memory_graph_bans_as_friction(
    report: Any,
    advice: dict[str, Any] | None,
) -> int:
    """Mirror newly banned genes from memory_graph into living memory (once per gene)."""
    from evolver.gep.memory_graph import patch_sync_state, read_sync_state  # noqa: PLC0415

    if not advice:
        return 0
    banned = advice.get("bannedGeneIds") or set()
    if not isinstance(banned, set):
        banned = set(banned)
    if not banned:
        return 0

    notified = read_sync_state().get("ban_friction_notified") or {}
    if not isinstance(notified, dict):
        notified = {}

    captured = 0
    for gene_id in sorted(banned):
        gid = str(gene_id)
        if gid in notified:
            continue
        report.capture_friction(
            "memory_graph",
            f"gene {gid} auto-banned by outcome history",
            "avoid re-selecting; prefer repair or alternate gene",
            auto_encode=False,
        )
        notified[gid] = time.time()
        captured += 1

    if captured:
        patch_sync_state({"ban_friction_notified": notified})
    return captured


def serialize_memory_advice(advice: dict[str, Any] | None) -> dict[str, Any] | None:
    """JSON-safe memory_advice for solidify state / WebUI."""
    if not advice:
        return None
    out = dict(advice)
    banned = out.get("bannedGeneIds")
    if isinstance(banned, set):
        out["bannedGeneIds"] = sorted(banned)
    return out


def build_memory_sync_summary(
    *,
    last_run: dict[str, Any] | None = None,
    signals: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate living_memory ↔ memory_graph sync state for observers."""
    from evolver.gep.living_memory import load_living_memory  # noqa: PLC0415
    from evolver.gep.memory_graph import (  # noqa: PLC0415
        get_memory_advice,
        read_sync_state,
        try_read_memory_graph_events,
    )

    living = load_living_memory()
    sync_state = read_sync_state()
    lr = last_run or {}
    advice = lr.get("memory_advice")
    signals_list = list(signals or lr.get("signals") or [])
    if not advice:
        advice = get_memory_advice(signals=signals_list, genes=[])

    banned = advice.get("bannedGeneIds") or set()
    if not isinstance(banned, set):
        banned = set(banned)

    friction_events = [
        e for e in try_read_memory_graph_events(limit=500) if e.get("kind") == "friction"
    ]
    synced_map = sync_state.get("living_memory_friction") or {}
    if not isinstance(synced_map, dict):
        synced_map = {}
    ban_notified = sync_state.get("ban_friction_notified") or {}
    if not isinstance(ban_notified, dict):
        ban_notified = {}

    preflight_pending = False
    try:
        from evolver.gep.autopoiesis import read_preflight_abort_report  # noqa: PLC0415

        preflight_pending = read_preflight_abort_report() is not None
    except Exception:
        pass

    return {
        "preflight_abort_pending": preflight_pending,
        "living_memory_loaded": bool(living.get("loaded")),
        "living_memory_friction_total": int(living.get("total_friction_points") or 0),
        "living_memory_categories": list(living.get("all_categories") or [])[:8],
        "synced_friction_ids": len(synced_map),
        "ban_friction_notified": len(ban_notified),
        "friction_events_in_graph": len(friction_events),
        "friction_categories": list(advice.get("frictionCategories") or []),
        "banned_genes": sorted(banned),
        "preferred_gene": advice.get("preferredGeneId"),
        "solidify_preferred_gene": advice.get("solidifyPreferredGeneId"),
        "unified_hints_count": len(advice.get("livingMemoryHints") or []),
        "last_run_friction_synced": lr.get("memory_graph_friction_synced"),
    }


def reinforce_solidify_failure_in_graph(
    last_run: dict[str, Any],
    *,
    error: str,
) -> dict[str, Any]:
    """Mirror solidify failure into memory_graph friction (complements living_memory)."""
    from evolver.gep.memory_graph import record_friction_observation  # noqa: PLC0415

    signals = list(last_run.get("signals") or [])
    gene_id = str(last_run.get("selected_gene_id") or "?")
    friction = {
        "id": f"solidify_fail_{gene_id}",
        "category": "solidify",
        "description": f"solidify failed for gene {gene_id}: {error[:200]}",
    }
    event = record_friction_observation(
        signals=signals,
        friction=friction,
        source="solidify_failure",
        run_id=last_run.get("run_id"),
    )
    return {"friction_event_id": event.get("id"), "gene_id": gene_id}


def gene_ids_from_solidify_failure(last_run: dict[str, Any]) -> list[str]:
    """Extract gene ids worth banning after repeated solidify failures."""
    gene_id = last_run.get("selected_gene_id")
    return [str(gene_id)] if gene_id else []


def living_memory_score_adjustment(
    gene: dict[str, Any],
    *,
    living_memory_hints: list[str],
    signals: list[str],
) -> float:
    """Score delta from living-memory risks, memory_graph bans, and repair boosts."""
    delta = 0.0
    gid = str(gene.get("id", "")).lower()
    category = str(gene.get("category", "")).lower()
    patterns = [str(p).lower() for p in (gene.get("signals_match") or [])]

    for hint in living_memory_hints:
        if hint.startswith(MEMORY_GRAPH_BAN_PREFIX):
            banned_gid = hint[len(MEMORY_GRAPH_BAN_PREFIX) :].lower()
            if gid == banned_gid or banned_gid in gid:
                delta -= 0.5
        elif hint.startswith(MEMORY_GRAPH_PREFER_PREFIX):
            prefer_gid = hint[len(MEMORY_GRAPH_PREFER_PREFIX) :].lower()
            if gid == prefer_gid:
                delta += 0.35
        elif hint.startswith(FRICTION_CATEGORY_PREFIX):
            fr_cat = hint[len(FRICTION_CATEGORY_PREFIX) :].lower().replace("_", "")
            if fr_cat and fr_cat in gid.replace("_", ""):
                delta -= 0.2
            for pattern in patterns:
                if fr_cat in pattern.replace("_", ""):
                    delta -= 0.15
        elif hint.startswith("living_memory_risk:"):
            risk_cat = hint.split(":", 1)[1].lower().replace("_", "")
            if risk_cat and risk_cat in gid.replace("_", ""):
                delta -= 0.35
            for pattern in patterns:
                if risk_cat in pattern.replace("_", ""):
                    delta -= 0.25
        elif hint.startswith("autopoiesis:"):
            rule = hint.split(":", 1)[1].lower().replace("_guard", "")
            for pattern in patterns:
                if rule in pattern.replace("_", ""):
                    delta -= 0.3

    repair_tags = (
        "repair_loop",
        "autopoiesis:repair_loop_guard",
        "preflight_abort",
        "autopoiesis:preflight_abort",
    )
    if category == "repair" and any(tag in signals for tag in repair_tags):
        delta += 0.25

    return delta


__all__ = [
    "FRICTION_CATEGORY_PREFIX",
    "MEMORY_GRAPH_BAN_PREFIX",
    "MEMORY_GRAPH_PREFER_PREFIX",
    "bidirectional_memory_sync",
    "build_memory_sync_summary",
    "capture_memory_graph_bans_as_friction",
    "gene_ids_from_solidify_failure",
    "reinforce_solidify_failure_in_graph",
    "serialize_memory_advice",
    "living_memory_score_adjustment",
    "living_memory_signal_hints",
    "memory_graph_signal_hints",
    "merge_bidirectional_advice",
    "merge_hints_into_signals",
    "merge_living_memory_into_advice",
    "merge_unified_hints",
    "sync_living_friction_to_memory_graph",
]
