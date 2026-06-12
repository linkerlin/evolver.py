"""GEP advanced cognition orchestration.

Wires recall injection, exploration, curriculum, reflection, and conversation
distillation into the evolution pipeline.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from evolver.gep.feature_flags import is_enabled

logger = logging.getLogger(__name__)


def _parse_event_timestamp(ev: dict[str, Any]) -> float:
    raw = ev.get("timestamp")
    if isinstance(raw, (int, float)):
        return float(raw)
    ts = ev.get("ts")
    if not isinstance(ts, str) or not ts:
        return 0.0
    text = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


def as_recall_attempt(ev: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a memory-graph or legacy event into a recall candidate."""
    if ev.get("type") == "attempt":
        outcome = str(ev.get("outcome", "")).lower()
        if "success" not in outcome and "pass" not in outcome:
            return None
        signals = ev.get("signals_snapshot") or ev.get("signals", [])
        if not signals:
            return None
        return ev

    if ev.get("type") == "MemoryGraphEvent" and ev.get("kind") == "outcome":
        outcome_obj = ev.get("outcome") or {}
        if outcome_obj.get("status") != "success":
            return None
        signal = ev.get("signal") or {}
        signals = signal.get("signals") or []
        if not signals:
            return None
        gene = ev.get("gene") or {}
        blast = ev.get("blast_radius") or {}
        return {
            "type": "attempt",
            "event_id": ev.get("id", "unknown"),
            "timestamp": _parse_event_timestamp(ev),
            "outcome": "success",
            "signals_snapshot": signals,
            "mutation_summary": (
                f"{gene.get('id', 'unknown')} ({gene.get('category', 'gene')})".strip()
            ),
            "changed_files": [],
            "file_line_counts": {},
            "blast_radius": blast,
        }
    return None


def flatten_recall_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return legacy-style successful attempt records for recall search."""
    flat: list[dict[str, Any]] = []
    for ev in events:
        normalized = as_recall_attempt(ev)
        if normalized is not None:
            flat.append(normalized)
    return flat


def augment_signals(signals: list[str], *, max_explore_tasks: int = 5) -> list[str]:
    """Add exploration and curriculum signals when feature flags allow."""
    merged = list(signals)

    if is_enabled("enable_explore"):
        try:
            from evolver.gep.explore import top_exploration_signals

            exploration = top_exploration_signals(max_tasks=max_explore_tasks)
            if is_enabled("enable_curriculum"):
                from evolver.gep.curriculum import ingest_exploration_tasks, next_tasks

                ingest_exploration_tasks(exploration)
                for task in next_tasks(count=2):
                    token = f"curriculum_target:{task.task_id}"
                    if token not in merged:
                        merged.append(token)
            for sig in exploration:
                token = (
                    f"explore:{sig.get('task_type', 'task')}:"
                    f"{sig.get('file_path', '')}:{sig.get('line', 0)}"
                )
                if token not in merged:
                    merged.append(token)
                desc = sig.get("description", "")
                if desc and desc not in merged:
                    merged.append(desc[:120])
        except Exception as exc:
            logger.debug("[Cognition] explore augmentation skipped: %s", exc)

    return merged


def build_recall_section(signals: list[str]) -> str:
    """Build verified recall markdown for the GEP prompt."""
    if not is_enabled("enable_recall_inject"):
        return ""
    try:
        from evolver.gep.memory_graph import try_read_memory_graph_events
        from evolver.gep.recall_inject import format_recall_prompt, search_recalls
        from evolver.gep.recall_verifier import filter_valid_recalls

        events = try_read_memory_graph_events()
        recall_events = flatten_recall_events(events)
        matches = search_recalls(signals, events=recall_events)
        verified = filter_valid_recalls(matches, events=recall_events)
        return format_recall_prompt(verified)
    except Exception as exc:
        logger.warning("[Cognition] recall injection failed: %s", exc)
        return ""


def enrich_cycle_context(ctx: dict[str, Any]) -> dict[str, Any]:
    """Run lightweight cognition enrichment before gene selection."""
    if is_enabled("enable_auto_distill"):
        try:
            from evolver.gep.auto_distill_conv import distill_and_append

            distill_and_append()
        except Exception as exc:
            logger.debug("[Cognition] distill skipped: %s", exc)

    ctx["recall_section"] = build_recall_section(ctx.get("signals", []))
    return ctx


def post_solidify_hooks(
    event: dict[str, Any],
    last_run: dict[str, Any],
) -> dict[str, Any]:
    """After a successful solidify: memory outcome, reflection, epigenetics."""
    hooks: dict[str, Any] = {"ok": True}
    signals = list(last_run.get("signals", []))
    gene_id = last_run.get("selected_gene_id")
    selected_gene = {"id": gene_id} if gene_id else None
    outcome = event.get("outcome") or {}
    blast_radius = event.get("blast_radius") or {}

    if is_enabled("enable_memory_graph"):
        try:
            from evolver.gep.memory_graph import record_outcome

            record_outcome(
                signals=signals,
                selected_gene=selected_gene,
                outcome=outcome,
                blast_radius=blast_radius,
                run_id=last_run.get("run_id"),
            )
            hooks["memory_outcome"] = True
        except Exception as exc:
            hooks["memory_outcome_error"] = str(exc)

    task_id = last_run.get("curriculum_task_id")
    if task_id and is_enabled("enable_curriculum"):
        try:
            from evolver.gep.curriculum import advance_level, record_attempt as curriculum_record

            curriculum_record(str(task_id), success=outcome.get("status") == "success")
            hooks["curriculum_level"] = advance_level()
        except Exception as exc:
            hooks["curriculum_error"] = str(exc)

    if is_enabled("enable_reflection"):
        try:
            from evolver.gep.reflection import reflect, should_reflect

            last_ts = last_run.get("last_reflection_at")
            if should_reflect(last_reflection_timestamp=last_ts):
                delta = reflect(dry_run=False)
                hooks["reflection"] = delta.reason
        except Exception as exc:
            hooks["reflection_error"] = str(exc)

    mutation = last_run.get("mutation") or {}
    attempt_id = last_run.get("innovation_attempt_id")
    if attempt_id or mutation.get("category") == "innovate":
        try:
            from evolver.ops.innovation import record_innovation_outcome

            record_innovation_outcome(
                attempt_id=str(attempt_id or "unknown"),
                gene_id=gene_id,
                status=str(outcome.get("status") or "failed"),
                run_id=last_run.get("run_id"),
            )
            hooks["innovation_outcome"] = True
        except Exception as exc:
            hooks["innovation_outcome_error"] = str(exc)

    if outcome.get("status") == "success":
        try:
            from evolver.gep.autopoiesis import capture_solidify_success

            capture_solidify_success(event, last_run=last_run)
            hooks["autopoiesis_success"] = True
        except Exception as exc:
            hooks["autopoiesis_success_error"] = str(exc)

    if gene_id and outcome.get("status") == "success":
        try:
            from evolver.gep.asset_store import load_genes, upsert_gene
            from evolver.gep.epigenetics import (
                apply_mark,
                capture_env_fingerprint,
                env_fingerprint_key,
            )

            ctx_key = env_fingerprint_key(capture_env_fingerprint())
            for gene in load_genes():
                if gene.get("id") == gene_id:
                    apply_mark(gene, ctx_key, boost=0.5, created_at=time.time())
                    upsert_gene(gene)
                    hooks["epigenetic_boost"] = gene_id
                    break
        except Exception as exc:
            hooks["epigenetic_error"] = str(exc)

    return hooks


def record_solidify_failure(
    last_run: dict[str, Any],
    *,
    error: str,
) -> None:
    """Record a failed solidify attempt into the memory graph."""
    try:
        from evolver.gep.autopoiesis import capture_solidify_friction

        capture_solidify_friction(error, last_run=last_run)
    except Exception as exc:
        logger.debug("[Cognition] autopoiesis solidify friction skipped: %s", exc)

    if not is_enabled("enable_memory_graph"):
        return
    try:
        from evolver.gep.memory_bridge import reinforce_solidify_failure_in_graph
        from evolver.gep.memory_graph import record_outcome

        gene_id = last_run.get("selected_gene_id")
        record_outcome(
            signals=list(last_run.get("signals", [])),
            selected_gene={"id": gene_id} if gene_id else None,
            outcome={"status": "failed", "error": error},
            run_id=last_run.get("run_id"),
        )
        reinforce_solidify_failure_in_graph(last_run, error=error)
    except Exception as exc:
        logger.debug("[Cognition] failed to record solidify failure: %s", exc)

    gene_id = last_run.get("selected_gene_id")
    if not gene_id:
        return
    try:
        from evolver.gep.asset_store import load_genes, upsert_gene
        from evolver.gep.epigenetics import (
            capture_env_fingerprint,
            env_fingerprint_key,
            suppress_gene,
        )

        ctx_key = env_fingerprint_key(capture_env_fingerprint())
        for gene in load_genes():
            if gene.get("id") == gene_id:
                suppress_gene(gene, context=ctx_key)
                upsert_gene(gene)
                break
    except Exception as exc:
        logger.debug("[Cognition] epigenetic suppression skipped: %s", exc)


__all__ = [
    "as_recall_attempt",
    "augment_signals",
    "build_recall_section",
    "enrich_cycle_context",
    "flatten_recall_events",
    "post_solidify_hooks",
    "record_solidify_failure",
]
