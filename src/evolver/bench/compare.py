"""Paired comparison of two bench runs (S30) — "did the mutation actually help?"

No Node.js equivalent; evolver.py addition.

Exact two-sided binomial test on discordant pairs (the paired-sample
equivalent of McNemar's test), hand-written because the project's scoring
surface is stdlib-only. Known-value contract: (10 wins, 0 losses) →
2 / 2**10 ≈ 0.001953.

A verdict requires BOTH the correct direction AND p ≤ alpha; anything else
is honestly reported as "no_significant_difference".
"""

from __future__ import annotations

import math
from typing import Any

PASS_THRESHOLD = 0.5


def binom_two_sided(b: int, n: int) -> float:
    """Exact two-sided p-value for b successes in n fair-coin trials."""
    if n <= 0:
        return 1.0
    b = max(0, min(n, b))
    extreme = sum(math.comb(n, k) for k in range(n + 1) if abs(k - n / 2) >= abs(b - n / 2))
    return float(min(1.0, extreme / 2**n))


def _passes(per_task: list[dict[str, Any]]) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for row in per_task:
        score = row.get("score")
        out[str(row["id"])] = isinstance(score, (int, float)) and score >= PASS_THRESHOLD
    return out


def compare_runs(
    a: dict[str, Any],
    b: dict[str, Any],
    *,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Compare two run results (per_task lists over the SAME task set)."""
    pa, pb = _passes(a.get("per_task") or []), _passes(b.get("per_task") or [])
    if set(pa) != set(pb):
        missing_a = sorted(set(pb) - set(pa))
        missing_b = sorted(set(pa) - set(pb))
        raise ValueError(
            "task sets differ — comparison would be meaningless: "
            f"missing_in_a={missing_a} missing_in_b={missing_b}"
        )
    wins_a = sum(1 for tid in pa if pa[tid] and not pb[tid])
    wins_b = sum(1 for tid in pb if pb[tid] and not pa[tid])
    ties = len(pa) - wins_a - wins_b
    discordant = wins_a + wins_b
    p = binom_two_sided(min(wins_a, wins_b), discordant) if discordant else 1.0
    if p <= alpha and wins_a > wins_b:
        verdict = "a_better"
    elif p <= alpha and wins_b > wins_a:
        verdict = "b_better"
    else:
        verdict = "no_significant_difference"
    return {
        "wins_a": wins_a,
        "wins_b": wins_b,
        "ties": ties,
        "discordant": discordant,
        "p": p,
        "alpha": alpha,
        "verdict": verdict,
    }


__all__ = ["binom_two_sided", "compare_runs"]
