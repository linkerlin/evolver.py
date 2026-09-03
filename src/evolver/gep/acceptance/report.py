"""Acceptance-gate gray-scale report (Sprint 22.5).

Aggregates shadow-mode gate verdicts recorded on EvolutionEvents into
interception / false-kill metrics so the gate can be calibrated before it
is switched to enforcing. Pure function over event dicts — no I/O.

Methodology: DGM-style graded evaluation + gray-release practice
(演进方案.md §13.5 P1-7).
"""

from __future__ import annotations

from typing import Any


def summarize_acceptance(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize gate activity over EvolutionEvents.

    Metrics (shadow mode):
    - ``gated_runs``: events carrying an ``acceptance_result``
    - ``shadow_rejected``: verdicts that *would* reject (shadow markers)
    - ``interception_rate``: shadow_rejected / gated_runs
    - ``validation_disagreements``: shadow rejections where the validation
      cascade was green — the gate alone wanted to stop the mutation
      (false-kill proxy, since ground truth is unavailable mid-gray-scale)
    - ``false_kill_risk``: disagreements / shadow_rejected (None when 0)
    - ``window``: first/last gated-event timestamps (None when empty)
    """
    gated = [e for e in events if isinstance(e.get("acceptance_result"), dict)]
    shadow_rejected = [
        e
        for e in gated
        if e["acceptance_result"].get("shadow")
        and e["acceptance_result"].get("would_accept") is False
    ]
    disagreements = [
        e
        for e in shadow_rejected
        if isinstance(e.get("validation_report"), dict)
        and bool(e["validation_report"].get("overall_ok"))
    ]
    n_gated = len(gated)
    n_rej = len(shadow_rejected)
    timestamps = [str(e.get("timestamp")) for e in gated if e.get("timestamp")]
    return {
        "gated_runs": n_gated,
        "shadow_rejected": n_rej,
        "interception_rate": round(n_rej / n_gated, 4) if n_gated else 0.0,
        "validation_disagreements": len(disagreements),
        "false_kill_risk": round(len(disagreements) / n_rej, 4) if n_rej else None,
        "window": {
            "first": min(timestamps) if timestamps else None,
            "last": max(timestamps) if timestamps else None,
        },
    }


def gate_soak_recommendation(metrics: dict[str, Any]) -> dict[str, Any]:
    """Promotion verdict for the acceptance gate's soak window.

    Pure heuristics over the shadow metrics; the actual switch to enforcement
    (``EVOLVER_ACCEPTANCE_SHADOW=0``) stays a human decision — this reports
    whether the data supports it.
    """
    from evolver.config import (
        GATE_SOAK_INTERCEPT_MAX,
        GATE_SOAK_INTERCEPT_MIN,
        GATE_SOAK_MAX_FALSE_KILL,
        GATE_SOAK_MIN_RUNS,
    )

    gated = int(metrics.get("gated_runs", 0))
    interception = float(metrics.get("interception_rate", 0.0))
    false_kill = metrics.get("false_kill_risk")
    reasons: list[str] = []

    if gated < GATE_SOAK_MIN_RUNS:
        verdict = "collecting"
        reasons.append(f"gated_runs={gated} < {GATE_SOAK_MIN_RUNS}: 继续积累 shadow 样本")
    elif false_kill is not None and false_kill > GATE_SOAK_MAX_FALSE_KILL:
        verdict = "false_kill_high"
        reasons.append(
            f"false_kill_risk={false_kill} > {GATE_SOAK_MAX_FALSE_KILL}: 门过紧，先校准再转正"
        )
    elif interception > GATE_SOAK_INTERCEPT_MAX:
        verdict = "over_intercepting"
        reasons.append(
            f"interception_rate={interception} > {GATE_SOAK_INTERCEPT_MAX}: 拦截过半，疑似过紧"
        )
    elif interception < GATE_SOAK_INTERCEPT_MIN:
        verdict = "under_intercepting"
        reasons.append(
            f"interception_rate={interception} < {GATE_SOAK_INTERCEPT_MIN}: 几乎未拦截"
            "（或代码确属健康——转正收益有限但风险亦低）"
        )
    else:
        verdict = "ready"
        reasons.append(
            f"样本 {gated} ≥ {GATE_SOAK_MIN_RUNS}，interception={interception} 落在 "
            f"[{GATE_SOAK_INTERCEPT_MIN}, {GATE_SOAK_INTERCEPT_MAX}]，"
            f"false_kill={false_kill} ≤ {GATE_SOAK_MAX_FALSE_KILL}"
        )

    return {
        "verdict": verdict,
        "shadow_mode": "on (EVOLVER_ACCEPTANCE_SHADOW default)",
        "criteria": {
            "min_runs": GATE_SOAK_MIN_RUNS,
            "interception_band": [GATE_SOAK_INTERCEPT_MIN, GATE_SOAK_INTERCEPT_MAX],
            "max_false_kill": GATE_SOAK_MAX_FALSE_KILL,
        },
        "reasons": reasons,
        "enforce_hint": "EVOLVER_ACCEPTANCE_SHADOW=0（转正由人类决定）",
    }


__all__ = ["gate_soak_recommendation", "summarize_acceptance"]
