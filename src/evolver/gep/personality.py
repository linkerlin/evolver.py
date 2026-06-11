"""Personality state management for the evolution engine.

Equivalent to evolver/src/gep/personality.js.
Personality influences strategy selection, mutation risk level,
and drift intensity. It adapts based on recent outcomes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evolver.gep.paths import get_evolver_settings_dir

DEFAULT_PERSONALITY: dict[str, float] = {
    "rigor": 0.5,
    "creativity": 0.5,
    "risk_tolerance": 0.3,
}


def _personality_path() -> Path:
    return get_evolver_settings_dir() / "personality.json"


def load_personality() -> dict[str, float]:
    """Load persisted personality or return defaults."""
    path = _personality_path()
    if not path.exists():
        return dict(DEFAULT_PERSONALITY)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            result = dict(DEFAULT_PERSONALITY)
            for k in DEFAULT_PERSONALITY:
                if k in data and isinstance(data[k], (int, float)):
                    result[k] = max(0.0, min(1.0, float(data[k])))
            return result
    except (OSError, json.JSONDecodeError):
        pass
    return dict(DEFAULT_PERSONALITY)


def save_personality(state: dict[str, float]) -> None:
    """Persist personality to disk."""
    path = _personality_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: max(0.0, min(1.0, float(v))) for k, v in state.items() if k in DEFAULT_PERSONALITY}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def adapt_personality(
    personality: dict[str, float] | None = None,
    recent_events: list[dict[str, Any]] | None = None,
) -> dict[str, float]:
    """Adapt personality based on recent evolution outcomes.

    Rules:
      - Success → slightly increase creativity and risk tolerance
      - Failure → increase rigor, decrease risk tolerance
      - Repair loop → boost rigor, suppress creativity
      - Innovation success → boost creativity
    """
    p = dict(personality) if personality else load_personality()
    events = list(recent_events or [])
    if not events:
        return p

    # Look at last 5 events
    tail = events[-5:]
    success_count = sum(1 for e in tail if (e.get("outcome") or {}).get("status") == "success")
    failure_count = len(tail) - success_count
    repair_count = sum(1 for e in tail if (e.get("mutation") or {}).get("category") == "repair")
    innovate_count = sum(1 for e in tail if (e.get("mutation") or {}).get("category") == "innovate")

    # Adjust rigor
    if failure_count >= 2:
        p["rigor"] = clamp(p["rigor"] + 0.1)
    elif success_count >= 3:
        p["rigor"] = clamp(p["rigor"] - 0.05)

    # Adjust creativity
    if repair_count >= 2:
        p["creativity"] = clamp(p["creativity"] - 0.1)
    elif innovate_count >= 1 and success_count >= innovate_count:
        p["creativity"] = clamp(p["creativity"] + 0.05)

    # Adjust risk_tolerance
    if failure_count >= 2:
        p["risk_tolerance"] = clamp(p["risk_tolerance"] - 0.1)
    elif success_count >= 3:
        p["risk_tolerance"] = clamp(p["risk_tolerance"] + 0.05)

    return p


def personality_to_strategy_bias(personality: dict[str, float] | None = None) -> dict[str, float]:
    """Convert personality into strategy category biases."""
    p = personality or load_personality()
    rigor = p.get("rigor", 0.5)
    creativity = p.get("creativity", 0.5)
    risk = p.get("risk_tolerance", 0.3)

    # Higher rigor → more repair, less innovate
    repair_bias = 0.34 + (rigor - 0.5) * 0.2
    innovate_bias = 0.33 + (creativity + risk - 0.8) * 0.2
    optimize_bias = 1.0 - repair_bias - innovate_bias

    return {
        "repair": clamp(repair_bias),
        "optimize": clamp(optimize_bias),
        "innovate": clamp(innovate_bias),
    }


def is_high_risk_personality(personality: dict[str, float] | None = None) -> bool:
    """Return True if personality leans toward high-risk mutations."""
    p = personality or load_personality()
    return p.get("rigor", 0.5) < 0.4 or p.get("risk_tolerance", 0.3) > 0.6


def is_conservative_personality(personality: dict[str, float] | None = None) -> bool:
    """Return True if personality leans toward conservative/low-risk."""
    p = personality or load_personality()
    return p.get("rigor", 0.5) > 0.7 and p.get("risk_tolerance", 0.3) < 0.3


__all__ = [
    "DEFAULT_PERSONALITY",
    "adapt_personality",
    "clamp",
    "is_conservative_personality",
    "is_high_risk_personality",
    "load_personality",
    "personality_to_strategy_bias",
    "save_personality",
]
