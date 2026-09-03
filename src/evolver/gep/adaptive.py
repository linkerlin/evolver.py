"""Feedback-adaptive mutation bias — EvoX adaptive-mutation-rate harvest.

EvoX's EvoPromptOptimizer adjusts its mutation rate from evaluation scores
(score < 0.3 → rate up to escape; score > 0.8 → rate down to refine). This
module ports that *contract* onto evolver's own semantics: the unified
evaluation feedback channel (gep/feedback.py, v1.99) now shifts strategy
weights, complementing the existing signal-based pivots (saturation →
steady-state) with an outcome-based source:

- **degraded streak** — the last ≥3 feedback reports are all degraded →
  ``explore_boost = -1`` (repair bias: double down on proven repair genes;
  evolver's native degraded-mode semantics)
- **converged plateau** — ≥3 reports, stddev < 0.01 (EvoX AFlow convergence
  criterion) and mean ≥ the degraded threshold → ``explore_boost = +1``
  (stable success → pivot to novelty, matching the plateau_pivot signals)
- otherwise neutral — small or mixed samples must not steer the engine.

No Node.js equivalent — Python-native design (concept harvest, no code
copied). Neutral by construction whenever the feedback journal is empty, so
non-swarm (CLI/daemon) users are unaffected.
"""

from __future__ import annotations

from typing import Any, Final

PLATEAU_STDDEV: Final = 0.01
DEGRADED_STREAK_MIN: Final = 3


def _row_is_degraded(row: dict[str, Any]) -> bool:
    from evolver.gep.feedback import EvaluationFeedback

    try:
        return EvaluationFeedback.model_validate(row).is_degraded()
    except Exception:
        return False


def _scores(rows: list[dict[str, Any]]) -> list[float]:
    out: list[float] = []
    for row in rows:
        score = row.get("primary_score")
        if isinstance(score, int | float):
            out.append(float(score))
    return out


def feedback_mutation_bias(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Map recent feedback reports onto a mutation-temperature verdict."""
    scores = _scores(rows)
    if len(scores) < DEGRADED_STREAK_MIN:
        return {
            "explore_boost": 0,
            "mode": "neutral",
            "n": len(scores),
            "reason": "insufficient feedback (need >= 3 reports)",
        }

    # Degraded streak: newest-first walk over the report list (newest last).
    streak = 0
    for row in reversed(rows):
        if not _row_is_degraded(row):
            break
        streak += 1
    if streak >= DEGRADED_STREAK_MIN:
        return {
            "explore_boost": -1,
            "mode": "repair_bias",
            "n": len(scores),
            "degraded_streak": streak,
            "reason": f"{streak} consecutive degraded reports — favor proven repairs",
        }

    mean = sum(scores) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)
    stddev = variance**0.5

    from evolver.config import SWARM_FEEDBACK_DEGRADED_THRESHOLD

    if stddev < PLATEAU_STDDEV and mean >= SWARM_FEEDBACK_DEGRADED_THRESHOLD:
        return {
            "explore_boost": 1,
            "mode": "explore_plateau",
            "n": len(scores),
            "mean": round(mean, 4),
            "stddev": round(stddev, 4),
            "reason": "converged on stable success (stddev < 0.01) — pivot to novelty",
        }

    return {
        "explore_boost": 0,
        "mode": "balanced",
        "n": len(scores),
        "mean": round(mean, 4),
        "stddev": round(stddev, 4),
        "reason": "mixed outcomes — keep baseline weights",
    }


def apply_adaptive_bias(policy: dict[str, Any], bias: dict[str, Any]) -> dict[str, Any]:
    """Shift a strategy-policy weight triple by the bias verdict.

    The three weights are re-normalized to sum to 1 and clamped to [0, 0.95];
    the verdict rides along as ``policy["adaptive"]`` so it lands in the GEP
    prompt's strategy_policy line and in cycle events.
    """
    from evolver.config import ADAPTIVE_MUTATION_SHIFT

    shifted = dict(policy)
    boost = int(bias.get("explore_boost", 0))
    if boost:
        shift = ADAPTIVE_MUTATION_SHIFT
        repair = float(shifted.get("repair", 0))
        optimize = float(shifted.get("optimize", 0))
        innovate = float(shifted.get("innovate", 0))
        if boost > 0:
            innovate += shift
        else:
            repair += shift
        total = repair + optimize + innovate
        if total > 0:
            repair, optimize, innovate = repair / total, optimize / total, innovate / total

        def clamp(v: float) -> float:
            return min(0.95, max(0.0, v))

        shifted["repair"] = round(clamp(repair), 3)
        shifted["optimize"] = round(clamp(optimize), 3)
        shifted["innovate"] = round(clamp(innovate), 3)
    shifted["adaptive"] = bias
    return shifted


__all__ = [
    "DEGRADED_STREAK_MIN",
    "PLATEAU_STDDEV",
    "apply_adaptive_bias",
    "feedback_mutation_bias",
]
