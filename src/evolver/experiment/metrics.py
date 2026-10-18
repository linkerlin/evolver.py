"""Experiment metrics — compute aggregate success/cost/latency metrics.

Equivalent to ``evolver/src/experiment/metrics.js``.

Aggregates a list of :class:`~agent_runner.TaskResult` into summary
statistics: success rate, average tokens, average latency, improvement
over baseline, and per-category breakdowns.
"""

from __future__ import annotations

from typing import Any, Final

from evolver.experiment.agent_runner import TaskResult

#: Cap copied from VISTA's step-efficiency term. Reference rounds default to 2:
#: finishing on round 2 scores 1.0; finishing on round 1 scores the cap.
RERE_CAP: Final = 1.15
RERE_REF_ROUNDS: Final = 2.0


def rere_score(
    *,
    accepted: bool,
    rounds_used: int,
    r_ref: float = RERE_REF_ROUNDS,
) -> float:
    """Relative evolution-round efficiency. Observational only — not a gate.

    ``min(cap, (r_ref / rounds_used) ** 2)`` when the session was accepted.
    A rejection scores 0. Extra rounds are punished on a square, so a fix
    that lands on round 1 outranks one that lands on round 4.
    """
    if not accepted or rounds_used < 1 or r_ref <= 0:
        return 0.0
    return round(min(RERE_CAP, (r_ref / float(rounds_used)) ** 2), 4)


def compute_metrics(results: list[TaskResult]) -> dict[str, Any]:
    """Compute aggregate metrics from a list of task results."""
    if not results:
        return {
            "total": 0,
            "success_rate": 0.0,
            "avg_tokens": 0.0,
            "avg_latency_s": 0.0,
        }

    total = len(results)
    successes = sum(1 for r in results if r.success)
    total_tokens = sum(r.tokens_used for r in results)
    total_latency = sum(r.latency_s for r in results)

    return {
        "total": total,
        "successes": successes,
        "failures": total - successes,
        "success_rate": round(successes / total, 4),
        "avg_tokens": round(total_tokens / total, 1) if total else 0.0,
        "avg_latency_s": round(total_latency / total, 2) if total else 0.0,
        "total_tokens": total_tokens,
    }


def compare_metrics(
    baseline: dict[str, Any],
    evolved: dict[str, Any],
) -> dict[str, Any]:
    """Compute improvement of evolved vs baseline metrics.

    Returns a dict with ``improvement`` fields (deltas and percentages).
    """
    base_rate = baseline.get("success_rate", 0.0)
    evo_rate = evolved.get("success_rate", 0.0)
    base_tokens = baseline.get("avg_tokens", 0.0)
    evo_tokens = evolved.get("avg_tokens", 0.0)

    rate_delta = round(evo_rate - base_rate, 4)
    token_delta = 0.0
    if base_tokens > 0:
        token_delta = round((evo_tokens - base_tokens) / base_tokens, 4)

    return {
        "success_rate_delta": rate_delta,
        "success_rate_pct": f"{rate_delta * 100:+.1f}%",
        "token_delta_pct": f"{token_delta * 100:+.1f}%",
        "evolved_better": rate_delta > 0 or (rate_delta == 0 and token_delta < 0),
    }


def format_report(
    baseline: dict[str, Any],
    evolved: dict[str, Any],
    comparison: dict[str, Any],
) -> str:
    """Format a human-readable experiment report."""
    lines = [
        "=" * 60,
        "  EVOLUTION EXPERIMENT REPORT",
        "=" * 60,
        "",
        "Baseline (no genes):",
        f"  Success rate: {baseline['success_rate']:.1%} "
        f"({baseline.get('successes', 0)}/{baseline['total']})",
        f"  Avg tokens:   {baseline['avg_tokens']:.0f}",
        f"  Avg latency:  {baseline['avg_latency_s']:.2f}s",
        "",
        "Evolved (with genes):",
        f"  Success rate: {evolved['success_rate']:.1%} "
        f"({evolved.get('successes', 0)}/{evolved['total']})",
        f"  Avg tokens:   {evolved['avg_tokens']:.0f}",
        f"  Avg latency:  {evolved['avg_latency_s']:.2f}s",
        "",
        "Comparison:",
        f"  Success rate: {comparison['success_rate_pct']}",
        f"  Token cost:   {comparison['token_delta_pct']}",
        f"  Verdict:      {'EVOLVED WINS' if comparison['evolved_better'] else 'BASELINE WINS'}",
        "=" * 60,
    ]
    return "\n".join(lines)


__all__ = [
    "RERE_CAP",
    "RERE_REF_ROUNDS",
    "compare_metrics",
    "compute_metrics",
    "format_report",
    "rere_score",
]
