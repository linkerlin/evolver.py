"""Acceptance-gate gray-scale report (Sprint 22.5).

Aggregates shadow-mode gate verdicts recorded on EvolutionEvents into
interception / false-kill metrics so the gate can be calibrated before it
is switched to enforcing. Pure function over event dicts — no I/O.

Methodology: DGM-style graded evaluation + gray-release practice
(演进方案.md §13.5 P1-7).

Round-30 verdict reachability (演进方案.md §11.4 P0-1), two corrections:

1. ``gated_cumulative`` — all-time gated count. ``gated_runs`` stays the
   rolling-window count, whose ceiling is ``GATE_SOAK_MIN_RUNS``; once the
   window filled, the phase metric saturated and could no longer express
   "still converging". Both numbers are reported now.
2. Promotion requires ≥1 **human-confirmed true positive**
   (``verified_true_positives``, counted from a read-only out-of-tree ledger
   handed in by the caller — this module stays I/O-free). Without the
   requirement a quiet window is indistinguishable from an untested gate;
   worse, once the pre-calibration false kills aged out of the window the old
   ``under_intercepting`` branch made ``ready`` **structurally unreachable**.
   A human-verified replacement is ``collecting_verified``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

#: Ledger verdict labels for human-reviewed gate decisions.
VERDICT_TRUE_POSITIVE: Final = "true_positive"
VERDICT_FALSE_KILL: Final = "false_kill"

#: Human-confirmed true positives required before promotion is even considered.
PROMOTION_MIN_VERIFIED_TP: Final = 1


def summarize_acceptance(
    events: list[dict[str, Any]],
    *,
    window_runs: int | None = None,
    verified: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Summarize gate activity over EvolutionEvents.

    Metrics (shadow mode):
    - ``gated_runs``: gated events **inside** the rolling evaluation window
    - ``gated_cumulative``: all-time gated events (window-independent)
    - ``shadow_rejected``: verdicts that *would* reject (shadow markers)
    - ``interception_rate``: shadow_rejected / gated_runs
    - ``validation_disagreements``: shadow rejections where the validation
      cascade was green — the gate alone wanted to stop the mutation
      (false-kill proxy, since ground truth is unavailable mid-gray-scale)
    - ``false_kill_risk``: disagreements / shadow_rejected (None when 0)
    - ``verified_true_positives`` / ``verified_false_kills``: all-time counts
      of gated events a human reviewed and labelled, via *verified*
      (``event_id -> VERDICT_*``)
    - ``window``: first/last gated-event timestamps (None when empty)
    - ``window_runs``: gated events actually inside the evaluation window

    Round-30 note: human verdicts are counted **all-time**, not per window —
    a confirmed true positive is durable evidence that the gate works, it
    should not expire because it slid out of a rolling sample.

    Round-24 rolling window: metrics cover the most recent ``window_runs``
    gated events (default :data:`GATE_SOAK_MIN_RUNS`, stable-sorted by
    timestamp). With an all-time window a pre-calibration flake never
    expired — the only way to dilute ``false_kill_risk`` below the
    promotion bar was accumulating ~9 more rejections, i.e. feeding bad
    mutations on purpose. The soak question is about the *calibrated*
    gate; samples older than the window age out naturally. Fewer gated
    events than the window → all included (collection phase unchanged).
    """
    from evolver.config import GATE_SOAK_MIN_RUNS

    if window_runs is None:
        window_runs = GATE_SOAK_MIN_RUNS
    gated_all = sorted(
        (e for e in events if isinstance(e.get("acceptance_result"), dict)),
        key=lambda e: str(e.get("timestamp") or ""),
    )
    gated = gated_all[-max(1, window_runs) :] if window_runs else gated_all
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
    verified_map = verified or {}
    all_ids = [str(e.get("id") or "") for e in gated_all]
    n_tp = sum(1 for i in all_ids if i and verified_map.get(i) == VERDICT_TRUE_POSITIVE)
    n_fk = sum(1 for i in all_ids if i and verified_map.get(i) == VERDICT_FALSE_KILL)
    return {
        "gated_runs": n_gated,
        "gated_cumulative": len(gated_all),
        "shadow_rejected": n_rej,
        "interception_rate": round(n_rej / n_gated, 4) if n_gated else 0.0,
        "validation_disagreements": len(disagreements),
        "false_kill_risk": round(len(disagreements) / n_rej, 4) if n_rej else None,
        "verified_true_positives": n_tp,
        "verified_false_kills": n_fk,
        "window": {
            "first": min(timestamps) if timestamps else None,
            "last": max(timestamps) if timestamps else None,
        },
        "window_runs": n_gated,
    }


def gate_soak_recommendation(metrics: dict[str, Any]) -> dict[str, Any]:
    """Promotion verdict for the acceptance gate's soak window.

    Pure heuristics over the shadow metrics; the actual switch to enforcement
    (``EVOLVER_ACCEPTANCE_SHADOW=0``) stays a human decision — this reports
    whether the data supports it.

    Round-30 ordering (演进方案.md §11.4 P0-1): sample maturity → **rejection
    quality** → human confirmation → interception volume. Calibration verdicts
    (false-kill / over-intercepting) outrank the confirmation floor because
    they are actionable: telling the operator "your gate is too tight" beats
    "you have no paperwork". Confirmation sits above the final ``ready``:
    zero rejections has two readings — a healthy repo, or a gate that never
    exercised its discrimination power — and only an adjudicated true
    positive tells them apart. It also unblocks a structural bug: with fewer
    than one confirmed true positive the old ``under_intercepting`` branch
    made ``ready`` unreachable forever.
    """
    from evolver.config import (
        GATE_SOAK_INTERCEPT_MAX,
        GATE_SOAK_INTERCEPT_MIN,
        GATE_SOAK_MAX_FALSE_KILL,
        GATE_SOAK_MIN_RUNS,
    )

    gated = int(metrics.get("gated_runs", 0) or 0)
    # Window-independent sample size; fall back to the windowed count so
    # hand-built metric dicts keep working.
    cumulative = int(metrics.get("gated_cumulative", gated) or 0)
    interception = float(metrics.get("interception_rate", 0.0) or 0.0)
    false_kill = metrics.get("false_kill_risk")
    verified_tp = int(metrics.get("verified_true_positives", 0) or 0)
    reasons: list[str] = []

    if cumulative < GATE_SOAK_MIN_RUNS:
        verdict = "collecting"
        reasons.append(
            f"gated_cumulative={cumulative} < {GATE_SOAK_MIN_RUNS}: 继续积累 shadow 样本"
            f"（窗内 {gated}）"
        )
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
    elif verified_tp < PROMOTION_MIN_VERIFIED_TP:
        verdict = "unverified"
        reasons.append(
            f"verified_true_positives={verified_tp} < {PROMOTION_MIN_VERIFIED_TP}: "
            "无人工确认真阳性——零拦截既可能是代码健康，也可能是门从未真正判别过；"
            "不足以支持转正（登记 gate-verifications.jsonl）"
        )
    elif interception < GATE_SOAK_INTERCEPT_MIN:
        verdict = "collecting_verified"
        reasons.append(
            f"interception_rate={interception} < {GATE_SOAK_INTERCEPT_MIN}: "
            f"窗内零拦截，但已有 {verified_tp} 次人工确认真阳性背书——"
            "校准后的安静期，不是门失灵；继续累积直至有带内读数"
        )
    else:
        verdict = "ready"
        reasons.append(
            f"样本 {cumulative} ≥ {GATE_SOAK_MIN_RUNS}（窗内 {gated}），"
            f"interception={interception} 落在 "
            f"[{GATE_SOAK_INTERCEPT_MIN}, {GATE_SOAK_INTERCEPT_MAX}]，"
            f"false_kill={false_kill} ≤ {GATE_SOAK_MAX_FALSE_KILL}，"
            f"人工确认真阳性 {verified_tp} ≥ {PROMOTION_MIN_VERIFIED_TP}"
        )

    return {
        "verdict": verdict,
        "shadow_mode": "on (EVOLVER_ACCEPTANCE_SHADOW default)",
        "criteria": {
            "min_runs": GATE_SOAK_MIN_RUNS,
            "interception_band": [GATE_SOAK_INTERCEPT_MIN, GATE_SOAK_INTERCEPT_MAX],
            "max_false_kill": GATE_SOAK_MAX_FALSE_KILL,
            "min_verified_true_positives": PROMOTION_MIN_VERIFIED_TP,
        },
        "reasons": reasons,
        "enforce_hint": "EVOLVER_ACCEPTANCE_SHADOW=0（转正由人类决定）",
    }


__all__ = [
    "PROMOTION_MIN_VERIFIED_TP",
    "VERDICT_FALSE_KILL",
    "VERDICT_TRUE_POSITIVE",
    "gate_soak_recommendation",
    "summarize_acceptance",
]
