"""Strategy / intent routing during evolution.

Equivalent to evolver/src/gep/strategy.js (obfuscated).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass
class Strategy:
    name: str
    label: str
    description: str
    repair: float
    optimize: float
    innovate: float
    explore: float = 0.0
    repair_loop_threshold: int = 3


STRATEGIES: dict[str, Strategy] = {
    "balanced": Strategy(
        name="balanced",
        label="Balanced",
        description="Equal weight across repair, optimize, and innovate.",
        repair=0.34,
        optimize=0.33,
        innovate=0.33,
        repair_loop_threshold=3,
    ),
    "innovate": Strategy(
        name="innovate",
        label="Innovation",
        description="Favor new capabilities and exploration.",
        repair=0.05,
        optimize=0.15,
        innovate=0.80,
        repair_loop_threshold=3,
    ),
    "harden": Strategy(
        name="harden",
        label="Hardening",
        description="Favor reliability and defensive improvements.",
        repair=0.50,
        optimize=0.40,
        innovate=0.10,
        repair_loop_threshold=3,
    ),
    "repair-only": Strategy(
        name="repair-only",
        label="Repair Only",
        description="Only attempt fixes for known failures.",
        repair=1.0,
        optimize=0.0,
        innovate=0.0,
        repair_loop_threshold=5,
    ),
    "early-stabilize": Strategy(
        name="early-stabilize",
        label="Early Stabilize",
        description="Favor repair early, then balance.",
        repair=0.50,
        optimize=0.30,
        innovate=0.20,
        repair_loop_threshold=2,
    ),
    "steady-state": Strategy(
        name="steady-state",
        label="Steady State",
        description="Minimal change, high reuse, low risk.",
        repair=0.20,
        optimize=0.60,
        innovate=0.20,
        repair_loop_threshold=6,
    ),
}


def get_strategy_names() -> list[str]:
    return list(STRATEGIES.keys())


def _force_innovation_env() -> bool:
    for key in ("FORCE_INNOVATION", "EVOLVE_FORCE_INNOVATION"):
        v = os.environ.get(key, "").lower().strip()
        if v in ("1", "true", "yes", "on"):
            return True
    return False


def resolve_strategy(ctx: dict[str, Any] | None = None) -> Strategy:
    ctx = ctx or {}
    signals = ctx.get("signals", []) or []

    env_strategy = os.environ.get("EVOLVE_STRATEGY", "").lower().strip()

    # Saturation signals override explicit strategy unless explicit is set and not auto
    saturation_signals = {"evolution_saturation", "force_steady_state"}
    if saturation_signals.intersection(signals):
        if env_strategy in ("", "auto"):
            return STRATEGIES["steady-state"]

    # Force innovation env var
    if _force_innovation_env() and env_strategy in ("", "auto"):
        return STRATEGIES["innovate"]

    if env_strategy and env_strategy != "auto":
        return STRATEGIES.get(env_strategy, STRATEGIES["balanced"])

    return STRATEGIES["balanced"]


__all__ = ["STRATEGIES", "Strategy", "get_strategy_names", "resolve_strategy"]
