"""Acceptance-gate decision logic.

Methodology inspired by Self-Harness (arXiv:2606.09498). No Node.js
equivalent; evolver.py self-research addition (Sprint A1).

Pure decision logic — no I/O, no LLM, fully unit-testable. The orchestrator
(:func:`run_acceptance_gate`) builds the :class:`LayerMetric` list and calls
:func:`decide`.

Decision rule (generalizes Self-Harness's two-split gate):

* every held-out tier present (T0/T1/T2) must NOT regress
  (verdict in ``dropped`` / ``regresses``);
* in ``strict_t2`` mode, any T2 ``unknown`` verdict also rejects;
* if a ``held_in`` layer is present, it MUST improve (full mode);
* if no ``held_in`` layer is present (T0-only degraded — B1 not enabled), the
  gate accepts iff no tier regressed (pure regression floor).

Self-Harness's gate is the special case where ``held_in`` is present and the
only held-out tier is T0.
"""

from __future__ import annotations

from evolver.gep.acceptance.schemas import (
    HELD_OUT_TIERS,
    REGRESS_VERDICTS,
    AcceptanceResult,
    LayerMetric,
    LayerVerdict,
    RepeatObs,
)


def mean_of(repeats: list[RepeatObs]) -> float:
    """Arithmetic mean of repeat scores; 0.0 when empty."""
    if not repeats:
        return 0.0
    return sum(r.score for r in repeats) / len(repeats)


def classify_rate(
    baseline_repeats: list[RepeatObs],
    candidate_repeats: list[RepeatObs],
    *,
    epsilon: float = 0.0,
) -> tuple[float, float, float, LayerVerdict]:
    """Classify a rate-based layer (held_in / T0) as improved/dropped/unchanged.

    *epsilon* is the minimum |delta| required to count as a change.
    """
    baseline_mean = mean_of(baseline_repeats)
    candidate_mean = mean_of(candidate_repeats)
    delta = candidate_mean - baseline_mean
    if delta > epsilon:
        verdict: LayerVerdict = "improved"
    elif delta < -epsilon:
        verdict = "dropped"
    else:
        verdict = "unchanged"
    return baseline_mean, candidate_mean, delta, verdict


def decide(
    layers: list[LayerMetric],
    *,
    strict_t2: bool = False,
    repeats: int = 1,
) -> AcceptanceResult:
    """Apply the acceptance decision rule to assembled *layers*."""
    by_kind = {layer.kind: layer for layer in layers}

    # 1. No held-out tier may regress.
    for kind in HELD_OUT_TIERS:
        tier = by_kind.get(kind)
        if tier is not None and tier.verdict in REGRESS_VERDICTS:
            return AcceptanceResult(
                accepted=False,
                layers=layers,
                reason=f"{kind}_regressed",
                repeats=repeats,
            )

    # 2. Strict T2: unknown also rejects.
    if strict_t2:
        t2 = by_kind.get("T2_synthetic")
        if t2 is not None and t2.verdict == "unknown":
            return AcceptanceResult(
                accepted=False,
                layers=layers,
                reason="T2_unknown_under_strict",
                repeats=repeats,
            )

    held_in = by_kind.get("held_in")
    if held_in is not None:
        # 3. Full mode: held_in must improve.
        if held_in.verdict != "improved":
            return AcceptanceResult(
                accepted=False,
                layers=layers,
                reason="held_in_not_improved",
                repeats=repeats,
            )
        return AcceptanceResult(
            accepted=True,
            layers=layers,
            reason="held_in_improved_and_no_tier_regressed",
            repeats=repeats,
        )

    # 4. T0-only degraded: no held_in → accept iff nothing regressed.
    return AcceptanceResult(
        accepted=True,
        layers=layers,
        reason="t0_only_no_regression",
        repeats=repeats,
    )


__all__ = [
    "classify_rate",
    "decide",
    "mean_of",
]
