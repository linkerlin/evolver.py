"""Paired comparison of two bench runs (S30) — "did the mutation actually help?"

No Node.js equivalent; evolver.py addition.

Exact two-sided binomial test on discordant pairs (the paired-sample
equivalent of McNemar's test), hand-written because the project's scoring
surface is stdlib-only. Known-value contract: (10 wins, 0 losses) →
2 / 2**10 ≈ 0.001953.

Also provides :func:`compare_paired_pareto` (Strategist S-5 / P3-2) combining
paired McNemar accuracy verification with Delta-method ratio SE and log-geometric
mean cost ratio for dual-route quality / efficiency adjudication.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

PASS_THRESHOLD = 0.5
PARETO_TIE_PP = 0.02
PARETO_TIE_COST = 0.02
PARETO_EFFICIENCY_RATIO_CAP = 0.65
PARETO_MAX_COST_ON_QUALITY_WIN = 1.05


def _z_for_alpha(alpha: float) -> float:
    """One-sided normal quantile approximation for common Pareto confidence thresholds."""
    if alpha <= 0.005:
        return 2.575829
    if alpha <= 0.01:
        return 2.326348
    if alpha <= 0.025:
        return 1.959964
    return 1.644854


def _task_cost(row: Mapping[str, Any], cost_key: str) -> float:
    for key in (cost_key, "weighted_cost", "tokens_used", "duration_ms", "latency_s"):
        val = row.get(key)
        if (
            isinstance(val, (int, float))
            and not isinstance(val, bool)
            and math.isfinite(float(val))
        ):
            return max(0.0, float(val))
    return 1.0


def _task_pass(row: Mapping[str, Any]) -> float:
    if "passed" in row and isinstance(row["passed"], bool):
        return 1.0 if row["passed"] else 0.0
    score = row.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        return 1.0 if float(score) >= PASS_THRESHOLD else 0.0
    if isinstance(row.get("success"), bool):
        return 1.0 if row["success"] else 0.0
    return 0.0


def compare_paired_pareto(
    arm_a: Mapping[str, Any],
    arm_b: Mapping[str, Any],
    *,
    alpha: float = 0.01,
    tie_pp: float = PARETO_TIE_PP,
    tie_cost: float = PARETO_TIE_COST,
    efficiency_ratio_cap: float = PARETO_EFFICIENCY_RATIO_CAP,
    max_cost_ratio_on_quality_win: float = PARETO_MAX_COST_ON_QUALITY_WIN,
    cost_key: str = "cost",
) -> dict[str, Any]:
    """Dual-route paired pass/cost Pareto adjudication (S-5 / --stage-exit v2).

    Evaluates *arm_a* (candidate/evolved) vs *arm_b* (baseline/placebo) over
    the identical task ID set:
    - ``quality_win``: McNemar exact ``p <= alpha`` with ``wins_a > wins_b``,
      accuracy gain ``d > tie_pp``, external slice net wins ``> 0`` (when present),
      and total cost ratio ``rho <= max_cost_ratio_on_quality_win``.
    - ``efficiency_win``: non-negative accuracy delta ``d >= 0.0`` (and external
      slice net wins ``>= 0`` when present) with upper confidence bound
      ``rho + z * se_rho <= efficiency_ratio_cap``.
    - Otherwise ``keep_baseline``.
    """
    rows_a = {str(r["id"]): r for r in (arm_a.get("per_task") or []) if isinstance(r, Mapping)}
    rows_b = {str(r["id"]): r for r in (arm_b.get("per_task") or []) if isinstance(r, Mapping)}
    if set(rows_a) != set(rows_b):
        missing_a = sorted(set(rows_b) - set(rows_a))
        missing_b = sorted(set(rows_a) - set(rows_b))
        raise ValueError(
            "task sets differ — paired Pareto comparison requires matching IDs: "
            f"missing_in_a={missing_a} missing_in_b={missing_b}"
        )

    keys = sorted(rows_a)
    n = len(keys)
    if n == 0:
        raise ValueError("cannot compare empty task sets")

    sa = [_task_pass(rows_a[k]) for k in keys]
    sb = [_task_pass(rows_b[k]) for k in keys]
    ca = [_task_cost(rows_a[k], cost_key) for k in keys]
    cb = [_task_cost(rows_b[k], cost_key) for k in keys]

    diffs = [a - b for a, b in zip(sa, sb, strict=True)]
    d = sum(diffs) / n
    se_d = math.sqrt(sum((x - d) ** 2 for x in diffs) / (n - 1) / n) if n > 1 else 0.0

    wins_a = sum(1 for a, b in zip(sa, sb, strict=True) if a > b)
    wins_b = sum(1 for a, b in zip(sa, sb, strict=True) if b > a)
    ties = n - wins_a - wins_b
    discordant = wins_a + wins_b
    p_mcnemar = binom_two_sided(min(wins_a, wins_b), discordant) if discordant else 1.0

    sum_ca = sum(ca)
    sum_cb = sum(cb)
    denom = max(sum_cb, 1e-9)
    rho = sum_ca / denom
    if n > 1:
        residuals = [a - rho * b for a, b in zip(ca, cb, strict=True)]
        se_rho = math.sqrt(sum(r * r for r in residuals) * n / (n - 1)) / denom
    else:
        se_rho = 0.0

    # Log-geometric mean across per-task ratios prevents extreme single-task
    # small-denominator outliers (e.g., 32x) from distorting the summary.
    log_ratios = [math.log(max(a, 1e-6) / max(b, 1e-6)) for a, b in zip(ca, cb, strict=True)]
    rho_geometric = math.exp(sum(log_ratios) / n)

    by_slice: dict[str, dict[str, Any]] = {}
    for idx, tid in enumerate(keys):
        sl = str(rows_a[tid].get("slice") or rows_b[tid].get("slice") or "").strip()
        if not sl:
            continue
        bucket = by_slice.setdefault(
            sl,
            {"n": 0, "wins_a": 0, "wins_b": 0, "sum_ca": 0.0, "sum_cb": 0.0},
        )
        bucket["n"] += 1
        if sa[idx] > sb[idx]:
            bucket["wins_a"] += 1
        elif sb[idx] > sa[idx]:
            bucket["wins_b"] += 1
        bucket["sum_ca"] += ca[idx]
        bucket["sum_cb"] += cb[idx]

    for bucket in by_slice.values():
        bucket["net_wins"] = bucket["wins_a"] - bucket["wins_b"]
        bucket["rho"] = round(bucket["sum_ca"] / max(bucket["sum_cb"], 1e-9), 6)

    ext_slice = by_slice.get("external")
    ext_net_wins = int(ext_slice["net_wins"]) if ext_slice is not None else None

    z = _z_for_alpha(alpha)
    quality_ok = (
        wins_a > wins_b
        and p_mcnemar <= alpha
        and d > tie_pp
        and rho <= max_cost_ratio_on_quality_win
        and (ext_net_wins is None or ext_net_wins > 0)
    )
    efficiency_ok = (
        d >= 0.0
        and (ext_net_wins is None or ext_net_wins >= 0)
        and (rho + z * se_rho) <= efficiency_ratio_cap
    )

    if quality_ok:
        verdict = "quality_win"
    elif efficiency_ok:
        verdict = "efficiency_win"
    else:
        verdict = "keep_baseline"

    return {
        "n": n,
        "alpha": alpha,
        "tie_pp": tie_pp,
        "tie_cost": tie_cost,
        "pass_rate_a": round(sum(sa) / n, 6),
        "pass_rate_b": round(sum(sb) / n, 6),
        "d": round(d, 6),
        "se_d": round(se_d, 6),
        "wins_a": wins_a,
        "wins_b": wins_b,
        "ties": ties,
        "discordant": discordant,
        "p_mcnemar": p_mcnemar,
        "total_cost_a": round(sum_ca, 6),
        "total_cost_b": round(sum_cb, 6),
        "rho": round(rho, 6),
        "se_rho": round(se_rho, 6),
        "rho_upper_ci": round(rho + z * se_rho, 6),
        "rho_geometric": round(rho_geometric, 6),
        "by_slice": by_slice,
        "external_net_wins": ext_net_wins,
        "verdict": verdict,
    }


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


__all__ = [
    "PARETO_EFFICIENCY_RATIO_CAP",
    "PARETO_MAX_COST_ON_QUALITY_WIN",
    "PARETO_TIE_COST",
    "PARETO_TIE_PP",
    "binom_two_sided",
    "compare_paired_pareto",
    "compare_runs",
]
