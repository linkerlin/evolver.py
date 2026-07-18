"""TTT-inspired evolution helpers (predictive boost, frontier, multi-gene).

Ports the behavioural surface covered by Node ``test/tttInspired.test.js``:
signal-clarity predictive boost, curriculum frontier flags, and multi-gene
chunk selection helpers used by the selector / memory graph.
"""

from __future__ import annotations

from typing import Any

# Actionable signals raise clarity; decorative ones dilute it.
_ACTIONABLE_BASES: frozenset[str] = frozenset(
    {
        "log_error",
        "error",
        "failed",
        "exception",
        "crash",
        "timeout",
        "timeout_error",
        "perf_bottleneck",
        "latency",
        "throughput",
        "slow",
        "capability_gap",
        "feature_request",
        "curriculum_target",
    }
)
_DECORATIVE_BASES: frozenset[str] = frozenset(
    {
        "stable_success_plateau",
        "memory_missing",
        "stable_no_error",
        "stable_success",
    }
)

_EPOCH_RESET_SIGNALS: frozenset[str] = frozenset(
    {
        "consecutive_failure_streak_5",
        "failure_loop_detected",
    }
)


def _signal_base(signal: str) -> str:
    return str(signal or "").split(":", 1)[0].strip().lower()


def is_frontier_signal(signal: str) -> bool:
    """True for curriculum frontier targets: ``curriculum_target:frontier:...``."""
    s = str(signal or "")
    return s.startswith("curriculum_target:frontier") or ":frontier:" in s


def compute_predictive_boost(
    *,
    signals: list[str] | None = None,
    baseline_observed: dict[str, Any] | None = None,  # noqa: ARG001 — Node parity
    current_observed: dict[str, Any] | None = None,  # noqa: ARG001 — Node parity
) -> dict[str, Any]:
    """Score signal clarity and a small predictive score boost.

    Returns ``{boost, signal_clarity, frontier_touched}``.
    """
    sigs = [str(s) for s in (signals or []) if s is not None]
    if not sigs:
        return {"boost": 0.0, "signal_clarity": 0.0, "frontier_touched": False}

    frontier_touched = any(is_frontier_signal(s) for s in sigs)
    actionable = 0
    decorative = 0
    for s in sigs:
        base = _signal_base(s)
        lower = s.lower()
        if base in _ACTIONABLE_BASES or any(a in lower for a in _ACTIONABLE_BASES):
            actionable += 1
        if base in _DECORATIVE_BASES:
            decorative += 1

    total = max(1, len(sigs))
    # Clarity in [0, 1]: actionable mass vs decorative dilution.
    raw = (actionable - 0.5 * decorative) / total
    signal_clarity = max(0.0, min(1.0, raw))

    boost = 0.0
    if actionable > 0:
        boost = 0.05 + 0.12 * signal_clarity
    elif decorative > 0:
        boost = -0.02 * min(1.0, decorative / total)
    if frontier_touched:
        boost += 0.05
    # Keep empty-adjacent range for low-signal cases.
    boost = max(-0.1, min(0.35, boost))

    return {
        "boost": float(boost),
        "signal_clarity": float(signal_clarity),
        "frontier_touched": bool(frontier_touched),
    }


def should_reset_epoch(signals: list[str] | None) -> tuple[bool, str]:
    """Return ``(should_reset, reason)`` for epoch-boundary signals."""
    for s in signals or []:
        base = _signal_base(s)
        if base in _EPOCH_RESET_SIGNALS or s in _EPOCH_RESET_SIGNALS:
            return True, base
        # Allow suffix form consecutive_failure_streak_5
        if "consecutive_failure_streak" in str(s).lower():
            return True, "consecutive_failure_streak_5"
        if "failure_loop_detected" in str(s).lower():
            return True, "failure_loop_detected"
    return False, ""


def curriculum_frontier_signals(task_ids: list[str]) -> list[str]:
    """Build signal tokens for curriculum frontier tasks."""
    return [f"curriculum_target:frontier:{tid}" for tid in task_ids if tid]


__all__ = [
    "compute_predictive_boost",
    "curriculum_frontier_signals",
    "is_frontier_signal",
    "should_reset_epoch",
]
