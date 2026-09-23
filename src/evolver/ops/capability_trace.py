"""Capability trajectory — P2-10 soak report v2 (RSI 演进对照.md).

A single verdict word (``collecting`` / ``unverified``) carries an order of
magnitude less information than a normalized margin map. This module renders
the HCI-style trajectory: each dimension is normalized from the dogfood
starting point (0) to its charter target (100), so the operator sees HOW FAR
along each axis the engine is — not just whether an opaque gate passed.

Pure function over existing metrics (same sources as charter-check);
verdict semantics stay with ``gate_soak_recommendation`` — a full-green
trajectory NEVER implies promotion readiness (the criteria are independent).
"""

from __future__ import annotations

from typing import Any, Final

#: (key, label, target) per dimension. ``now`` values are supplied by the
#: caller from live instruments. Targets mirror the charter (演进方案.md §10):
#: ≥20 gated samples, ≥16 anchor probes, verdict-flip headroom (cumulative
#: ≥40 gives the two historical false-kills room to age out), sub-second
#: cycle overhead.
DIMENSIONS: Final[list[tuple[str, str, float]]] = [
    ("gated_cumulative", "gated samples", 40.0),
    ("anchor_cases", "anchor probes", 16.0),
    ("env_headroom", "env budget headroom", 20.0),
]


def capability_trajectory(
    *,
    gated_cumulative: int,
    anchor_cases: int,
    env_count: int,
    env_budget: int = 80,
) -> dict[str, Any]:
    """Normalize live readings into a 0-100 margin map (pure function).

    Each dimension: ``pct = clamp(now / target * 100, 0, 100)``. ``env_headroom``
    is inverted (budget minus usage) — spending LESS of the env budget is
    progress. Values above target clamp at 100 (margin, not infinity).
    """
    env_headroom = max(0, env_budget - env_count)
    now_by_key = {
        "gated_cumulative": gated_cumulative,
        "anchor_cases": anchor_cases,
        "env_headroom": env_headroom,
    }
    dims: list[dict[str, Any]] = []
    for key, label, target in DIMENSIONS:
        now = now_by_key.get(key, 0)
        pct = round(max(0.0, min(100.0, now / target * 100.0)), 1)
        dims.append({"key": key, "label": label, "now": now, "target": target, "pct": pct})
    overall = round(sum(d["pct"] for d in dims) / len(dims), 1) if dims else 0.0
    return {"dimensions": dims, "overall_pct": overall}


__all__ = ["DIMENSIONS", "capability_trajectory"]
