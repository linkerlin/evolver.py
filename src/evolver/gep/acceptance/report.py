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
    return {
        "gated_runs": n_gated,
        "shadow_rejected": n_rej,
        "interception_rate": round(n_rej / n_gated, 4) if n_gated else 0.0,
        "validation_disagreements": len(disagreements),
        "false_kill_risk": round(len(disagreements) / n_rej, 4) if n_rej else None,
    }


__all__ = ["summarize_acceptance"]
