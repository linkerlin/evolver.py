"""Signals phase: extract and deduplicate signals.

Equivalent to evolver/src/evolve/pipeline/signals.js.
"""

from __future__ import annotations

from typing import Any

from evolver.gep.asset_store import consume_pending_signals, load_capsules, load_genes
from evolver.gep.cognition import augment_signals
from evolver.gep.signals import extract_signals as gep_extract_signals

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

    signals = gep_extract_signals(
        recent_session_transcript=corpus,
        memory_snippet="",
        user_snippet="",
        recent_events=ctx.get("recent_events", []),
    )
    # Append pending signals (they were consumed; re-inject)
    for s in pending:
        if s not in signals:
            signals.append(s)

    signals = augment_signals(signals)
    ctx["signals"] = signals
    ctx["genes"] = load_genes()
    ctx["capsules"] = load_capsules()
    ctx["recent_events"] = ctx.get("recent_events", [])
    ctx["skip_hub_calls"] = should_skip_hub_calls(signals)
    return ctx
