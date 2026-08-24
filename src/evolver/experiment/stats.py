"""Thesis statistics — two-proportion A/B verdicts with power guidance.

Concept harvest from Node v2 ``benchmark/thesis.d.ts`` (behavioral
re-implementation; no code copied). A verdict that evolution actually
helped requires ALL THREE of:

1. **practical delta** — observed rate gap ≥ ``min_delta`` (default 0.05)
2. **statistical significance** — pooled-variance two-proportion z-test
   at ``alpha`` (default 0.05, two-sided)
3. **adequate sample** — both arms ≥ ``min_n`` (default 30)

Plus Wald CI and achieved-power/required-n guidance so a failed verdict
says whether to collect more data or accept the null.

Pure stdlib; no scipy. Sprint 24.9 (演进方案.md §9 概念收割 #11).
"""

from __future__ import annotations

import math
from typing import Any

MIN_DELTA: float = 0.05
ALPHA: float = 0.05
MIN_N: int = 30
TARGET_POWER: float = 0.8

_Z_975: float = 1.959963984540054  # two-sided 95% normal quantile
_Z_POWER: dict[float, float] = {0.8: 0.8416212335729143, 0.9: 1.2815515655446004}


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse CDF via bisection on the erf-based CDF (sufficient at 1e-6)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    lo, hi = -8.0, 8.0
    for _ in range(64):
        mid = (lo + hi) / 2.0
        if _norm_cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def two_proportion_z_test(
    successes_a: int, n_a: int, successes_b: int, n_b: int
) -> dict[str, float]:
    """Pooled-variance two-proportion z-test (H0: p_b == p_a)."""
    if n_a <= 0 or n_b <= 0:
        raise ValueError("both arms need n > 0")
    p_pool = (successes_a + successes_b) / (n_a + n_b)
    se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / n_a + 1.0 / n_b))
    if se == 0.0:
        return {"z": 0.0, "p_value": 1.0}
    z = ((successes_b / n_b) - (successes_a / n_a)) / se
    p_value = 2.0 * (1.0 - _norm_cdf(abs(z)))
    return {"z": round(z, 6), "p_value": round(min(1.0, max(0.0, p_value)), 6)}


def wald_ci(
    successes_a: int,
    n_a: int,
    successes_b: int,
    n_b: int,
    *,
    alpha: float = ALPHA,
) -> list[float]:
    """Wald CI for (p_b - p_a), unpaired proportions."""
    p_a, p_b = successes_a / n_a, successes_b / n_b
    z = _norm_ppf(1.0 - alpha / 2.0)
    se = math.sqrt(p_a * (1 - p_a) / n_a + p_b * (1 - p_b) / n_b)
    delta = p_b - p_a
    return [round(delta - z * se, 6), round(delta + z * se, 6)]


def achieved_power(
    successes_a: int,
    n_a: int,
    successes_b: int,
    n_b: int,
    *,
    alpha: float = ALPHA,
) -> float:
    """Normal-approx power of this sample size under the observed effect."""
    p_a, p_b = successes_a / n_a, successes_b / n_b
    if abs(p_b - p_a) == 0.0:
        return 0.0
    p_bar = (successes_a + successes_b) / (n_a + n_b)
    se_h0 = math.sqrt(p_bar * (1 - p_bar) * (2.0 / ((n_a + n_b) / 2)))
    se_h1 = math.sqrt(p_a * (1 - p_a) / n_a + p_b * (1 - p_b) / n_b)
    if se_h1 == 0.0:
        return 0.0
    z_alpha = _norm_ppf(1.0 - alpha / 2.0)
    power = _norm_cdf((abs(p_b - p_a) - z_alpha * se_h0) / se_h1)
    return round(min(1.0, max(0.0, power)), 4)


def required_n_per_arm(
    p_a: float,
    p_b: float,
    *,
    alpha: float = ALPHA,
    power: float = TARGET_POWER,
) -> int:
    """Per-arm sample size needed to detect p_a → p_b at (alpha, power)."""
    if abs(p_b - p_a) == 0.0:
        raise ValueError("no effect to detect")
    z_alpha = _norm_ppf(1.0 - alpha / 2.0)
    z_beta = _Z_POWER.get(power) or _norm_ppf(power)
    p_bar = (p_a + p_b) / 2.0
    n = (
        (
            z_alpha * math.sqrt(2 * p_bar * (1 - p_bar))
            + z_beta * math.sqrt(p_a * (1 - p_a) + p_b * (1 - p_b))
        )
        / (p_b - p_a)
    ) ** 2
    return max(2, math.ceil(n))


def evaluate_thesis(
    successes_baseline: int,
    n_baseline: int,
    successes_evolved: int,
    n_evolved: int,
    *,
    min_delta: float = MIN_DELTA,
    alpha: float = ALPHA,
    min_n: int = MIN_N,
) -> dict[str, Any]:
    """Full thesis verdict: practical delta ∧ significance ∧ sample floor."""
    test = two_proportion_z_test(successes_baseline, n_baseline, successes_evolved, n_evolved)
    p_base = successes_baseline / n_baseline if n_baseline else 0.0
    p_evo = successes_evolved / n_evolved if n_evolved else 0.0
    observed_delta = p_evo - p_base

    verdict = "no_clear_improvement"
    if min(n_baseline, n_evolved) < min_n:
        verdict = "insufficient_samples"
    elif observed_delta >= min_delta and test["p_value"] < alpha:
        verdict = "evolved_better"
    elif observed_delta <= -min_delta and test["p_value"] < alpha:
        verdict = "worse"

    return {
        "verdict": verdict,
        "observed_delta": round(observed_delta, 6),
        "min_delta": min_delta,
        "z": test["z"],
        "p_value": test["p_value"],
        "significant": bool(test["p_value"] < alpha),
        "ci95": wald_ci(successes_baseline, n_baseline, successes_evolved, n_evolved),
        "achieved_power": achieved_power(
            successes_baseline, n_baseline, successes_evolved, n_evolved, alpha=alpha
        ),
        "required_n_per_arm": (
            None if abs(observed_delta) == 0.0 else required_n_per_arm(p_base, p_evo, alpha=alpha)
        ),
    }


__all__ = [
    "ALPHA",
    "MIN_DELTA",
    "MIN_N",
    "TARGET_POWER",
    "achieved_power",
    "evaluate_thesis",
    "required_n_per_arm",
    "two_proportion_z_test",
    "wald_ci",
]
