"""Signals phase: extract and deduplicate signals.

Equivalent to evolver/src/evolve/pipeline/signals.js.
"""

from __future__ import annotations

import logging
from typing import Any

from evolver.gep.asset_store import consume_pending_signals, load_capsules, load_genes
from evolver.gep.autopoiesis_rules import guard_check_signal_keys, merge_signal_keys
from evolver.gep.cognition import augment_signals
from evolver.gep.feature_flags import is_enabled
from evolver.gep.learning_signals import (
    gather_pipeline_learning_signals,
    is_learning_signals_enabled,
)
from evolver.gep.signals import extract_signals as gep_extract_signals

logger = logging.getLogger(__name__)

# Must match actionable signals that prevent saturation gating
_ACTIONABLE_SIGNALS = {
    "log_error",
    "external_task",
    "bounty_task",
}

_SATURATION_SIGNALS = {
    "force_steady_state",
    "evolution_saturation",
    "empty_cycle_loop_detected",
}


def should_skip_hub_calls(signals: list[str]) -> bool:
    """Saturation gating: skip Hub if only saturation signals and no actionable ones."""
    if not signals:
        return False
    has_actionable = any(
        sig in _ACTIONABLE_SIGNALS or sig.startswith("errsig:") or len(sig) > 21 for sig in signals
    )
    if has_actionable:
        return False
    return all(sig in _SATURATION_SIGNALS for sig in signals)


async def signals_phase(ctx: dict[str, Any]) -> dict[str, Any]:
    corpus = "\n\n".join(
        [
            ctx.get("memory_snippet", ""),
            ctx.get("user_snippet", ""),
            ctx.get("session_log", ""),
            ctx.get("recent_master_log", ""),
        ]
    )
    # Inject pending explicit signals into corpus via side-effect
    pending = consume_pending_signals()

    # Sprint 22.1 (§13.3-#1): feed EvolutionEvent history into the pipeline so
    # signal-history modulation (saturation / dedup / ban_gene / plateau) can fire.
    recent_events = ctx.get("recent_events")
    if not isinstance(recent_events, list) and is_enabled("enable_event_history"):
        try:
            from evolver.gep.asset_store import read_all_events

            recent_events = read_all_events()[-20:]
        except Exception as exc:
            logger.debug("[signals] event history load skipped: %s", exc)
    if not isinstance(recent_events, list):
        recent_events = []

    signals = gep_extract_signals(
        recent_session_transcript=corpus,
        memory_snippet="",
        user_snippet="",
        recent_events=recent_events,
    )

    # Sprint 22.1 (§13.3-#2): infer an outcome for the previous cycle's attempt
    # (error cleared => success) when no solidify outcome was ever recorded.
    # Only error-family signals count as "error persists" — boilerplate signals
    # like memory_missing must not mark an attempt failed.
    if is_enabled("enable_gap_outcome_inference"):
        error_signals = [
            s
            for s in signals
            if s == "log_error" or s.startswith(("errsig:", "recurring_errsig"))
        ]
        try:
            from evolver.gep.memory_graph import record_outcome_from_state

            record_outcome_from_state(signals=error_signals)
        except Exception as exc:
            logger.debug("[signals] gap outcome inference skipped: %s", exc)

    # Append pending signals (they were consumed; re-inject)
    for s in pending:
        if s not in signals:
            signals.append(s)

    signals = augment_signals(signals)
    if is_learning_signals_enabled():
        signals, learning_added = merge_signal_keys(signals, gather_pipeline_learning_signals())
        if learning_added:
            ctx["learning_signals_merged"] = learning_added
    signals, guard_added = merge_signal_keys(signals, guard_check_signal_keys())
    if guard_added:
        ctx["autopoiesis_guard_signals"] = guard_added
    try:
        from evolver.gep.autopoiesis import (
            apply_preflight_abort_recovery,
            preflight_abort_signal_keys,
        )

        signals, pfa_added = merge_signal_keys(signals, preflight_abort_signal_keys())
        if pfa_added:
            ctx["preflight_abort_signals_merged"] = pfa_added
        ctx["signals"] = signals
        if apply_preflight_abort_recovery(ctx):
            signals = list(ctx["signals"])
    except Exception:
        pass
    ctx["signals"] = signals
    ctx["genes"] = load_genes()
    ctx["capsules"] = load_capsules()
    ctx["recent_events"] = recent_events
    skip_hub = should_skip_hub_calls(signals)
    if ctx.get("preflight_abort_recovery"):
        skip_hub = True
        ctx.setdefault("hub_skip_reason", "preflight_abort_recovery")
    ctx["skip_hub_calls"] = skip_hub
    return ctx
