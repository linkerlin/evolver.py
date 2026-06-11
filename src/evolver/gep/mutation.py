"""Mutation engine for gene/capsule variants.

Equivalent to evolver/src/gep/mutation.js (obfuscated).
"""

from __future__ import annotations

import math
import secrets
import time
from typing import Any

from evolver.gep.schemas import VALID_CATEGORIES


def clamp01(value: float | None) -> float:
    if not isinstance(value, (int, float)):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def is_high_risk_personality(personality: dict[str, Any] | None) -> bool:
    if not personality:
        return False
    rigor = clamp01(personality.get("rigor"))
    risk_tolerance = clamp01(personality.get("risk_tolerance"))
    return rigor < 0.5 or risk_tolerance > 0.6


def is_high_risk_mutation_allowed(personality: dict[str, Any] | None) -> bool:
    if not personality:
        return False
    rigor = clamp01(personality.get("rigor"))
    risk_tolerance = clamp01(personality.get("risk_tolerance"))
    return rigor >= 0.6 and risk_tolerance <= 0.5


class Mutation(dict[str, Any]):
    """Mutation object backed by a dict for easy serialization."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__()
        self.update(kwargs)


def _choose_category(signals: list[str], drift_enabled: bool = False) -> str:
    if drift_enabled:
        return "innovate"
    lowered = [s.lower() for s in signals]
    error_hits = sum(
        1 for s in lowered if "error" in s or "exception" in s or "failed" in s or "errsig" in s
    )
    if error_hits > 0:
        return "repair"
    opportunity_hits = sum(
        1
        for s in lowered
        if s
        in (
            "user_feature_request",
            "user_improvement_suggestion",
            "capability_gap",
            "stable_success_plateau",
            "explore_opportunity",
        )
        or s.startswith("user_feature_request:")
        or s.startswith("user_improvement_suggestion:")
    )
    if opportunity_hits > 0:
        return "innovate"
    if "perf_bottleneck" in lowered:
        return "optimize"
    return "optimize"


def build_mutation(
    *,
    signals: list[str],
    selected_gene: dict[str, Any] | None = None,
    drift_enabled: bool = False,
    personality_state: dict[str, Any] | None = None,
    allow_high_risk: bool = False,
) -> Mutation:
    category = _choose_category(signals, drift_enabled=drift_enabled)

    high_risk_personality = is_high_risk_personality(personality_state)
    if category == "innovate" and high_risk_personality:
        category = "optimize"
        safety_note = "safety_downgrade_from_innovate"
        trigger_signals = list(signals) + [safety_note]
    else:
        trigger_signals = list(signals)

    risk_level = "low"
    if allow_high_risk and category in ("innovate", "explore"):
        if is_high_risk_mutation_allowed(personality_state):
            risk_level = "high"
        else:
            risk_level = "medium"
    if category == "repair":
        risk_level = "low"

    mutation_id = f"mut_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
    target = selected_gene.get("id") if selected_gene else None
    expected_effect = (
        f"Address signals: {', '.join(signals[:5])}" if signals else "No specific signal"
    )

    return Mutation(
        type="Mutation",
        id=mutation_id,
        category=category,
        trigger_signals=trigger_signals,
        target=target,
        expected_effect=expected_effect,
        risk_level=risk_level,
        drift_enabled=drift_enabled,
        gene_id=target,
    )


def is_valid_mutation(m: Any) -> bool:
    if not isinstance(m, dict):
        return False
    if m.get("type") != "Mutation":
        return False
    if not m.get("id"):
        return False
    if m.get("category") not in VALID_CATEGORIES:
        return False
    if not isinstance(m.get("trigger_signals"), list):
        return False
    if not isinstance(m.get("target"), (str, type(None))):
        return False
    if not isinstance(m.get("expected_effect"), str):
        return False
    if m.get("risk_level") not in ("low", "medium", "high"):
        return False
    return True


def normalize_mutation(m: dict[str, Any] | None) -> Mutation:
    if not isinstance(m, dict):
        m = {}
    return Mutation(
        type="Mutation",
        id=m.get("id") or f"mut_{int(time.time() * 1000)}_{secrets.token_hex(4)}",
        category=m.get("category", "optimize")
        if m.get("category") in VALID_CATEGORIES
        else "optimize",
        trigger_signals=list(m.get("trigger_signals", [])),
        target=m.get("target"),
        expected_effect=m.get("expected_effect", ""),
        risk_level=m.get("risk_level", "low")
        if m.get("risk_level") in ("low", "medium", "high")
        else "low",
    )


__all__ = [
    "Mutation",
    "build_mutation",
    "clamp01",
    "is_high_risk_mutation_allowed",
    "is_high_risk_personality",
    "is_valid_mutation",
    "normalize_mutation",
]
