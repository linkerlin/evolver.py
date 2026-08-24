"""Mutation engine for gene/capsule variants.

Equivalent to evolver/src/gep/mutation.js (obfuscated).
"""

from __future__ import annotations

import math
import random
import secrets
import time
from typing import Any

from evolver.gep.feature_flags import is_enabled
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


# Sprint 23.2: prior weight for the keyword-matched category vs alternatives
# (operator bandit keeps the signal semantics dominant while exploring).
_KEYWORD_PRIOR: float = 1.0
_ALTERNATIVE_PRIOR: float = 0.2
OPERATOR_UCB1_C: float = 1.0


def _category_stats() -> dict[str, dict[str, float]]:
    """Per-category graded-outcome stats from recent EvolutionEvents."""
    try:
        # Sprint 24.1 (enable_event_projection): derive via the shared replay
        # projector — same filter/window/shape as the historical inline scan.
        if is_enabled("enable_event_projection"):
            from evolver.gep.event_projection import scored_category_window

            return scored_category_window(window=50)

        from evolver.gep.asset_store import read_all_events

        stats: dict[str, dict[str, float]] = {}
        for evt in read_all_events()[-50:]:
            cat = (evt.get("mutation") or {}).get("category")
            score = (evt.get("outcome") or {}).get("score")
            if cat not in VALID_CATEGORIES or not isinstance(score, (int, float)):
                continue
            row = stats.setdefault(cat, {"attempts": 0.0, "score_sum": 0.0})
            row["attempts"] += 1
            row["score_sum"] += float(score)
        return stats
    except Exception:
        return {}


def _sample_category(keyword_category: str) -> str:
    """UCB1-weighted category sampling (Sprint 23.2, AOS/FRRMAB lineage).

    weight = prior * (1 + mean_score + C*sqrt(ln N / n_i)); untried categories
    get the max confidence term. The keyword category keeps the dominant
    prior so signal semantics stay in charge; the bandit only tips ties and
    learns from graded cascade outcomes.
    """
    stats = _category_stats()
    total = sum(row["attempts"] for row in stats.values())
    log_n = math.log(max(2.0, total))
    weights = []
    for cat in VALID_CATEGORIES:
        prior = _KEYWORD_PRIOR if cat == keyword_category else _ALTERNATIVE_PRIOR
        row = stats.get(cat)
        if row is None or row["attempts"] <= 0:
            exploration = OPERATOR_UCB1_C * math.sqrt(log_n)
        else:
            mean = row["score_sum"] / row["attempts"]
            exploration = OPERATOR_UCB1_C * (math.sqrt(log_n / row["attempts"]) + mean)
        weights.append(max(0.0, prior) * (1.0 + exploration))
    if not any(w > 0 for w in weights):
        return keyword_category
    return list(VALID_CATEGORIES)[
        random.choices(range(len(VALID_CATEGORIES)), weights=weights, k=1)[0]
    ]


def build_mutation(
    *,
    signals: list[str],
    selected_gene: dict[str, Any] | None = None,
    drift_enabled: bool = False,
    personality_state: dict[str, Any] | None = None,
    allow_high_risk: bool = False,
    force_category: str | None = None,
) -> Mutation:
    category = force_category or _choose_category(signals, drift_enabled=drift_enabled)
    if category not in VALID_CATEGORIES:
        category = _choose_category(signals, drift_enabled=drift_enabled)
    # Sprint 23.2 (enable_operator_bandit): sample the category with UCB1
    # weights over graded outcomes (force_category / drift stay authoritative).
    if (
        is_enabled("enable_operator_bandit")
        and not force_category
        and not drift_enabled
        and category in VALID_CATEGORIES
    ):
        category = _sample_category(category)

    high_risk_personality = is_high_risk_personality(personality_state)
    if category == "innovate" and high_risk_personality:
        category = "optimize"
        safety_note = "safety_downgrade_from_innovate"
        trigger_signals = [*list(signals), safety_note]
    else:
        trigger_signals = list(signals)

    risk_level = "low"
    if allow_high_risk and category in ("innovate", "explore"):
        risk_level = "high" if is_high_risk_mutation_allowed(personality_state) else "medium"
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
    return m.get("risk_level") in ("low", "medium", "high")


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
