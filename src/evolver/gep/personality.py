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

# Sprint 24.12 (enable_personality_v2): Node v2 five-axis vector with its own
# defaults — applied only when the flag is on (flag-off keeps 1.94 behavior).
PERSONALITY_V2_DEFAULTS: dict[str, float] = {
    "rigor": 0.7,
    "creativity": 0.35,
    "verbosity": 0.25,
    "risk_tolerance": 0.4,
    "obedience": 0.85,
}

AXES_V2: tuple[str, ...] = tuple(PERSONALITY_V2_DEFAULTS)

#: Bucket granularity for per-axis outcome statistics (Node v2: 0.1).
BUCKET_GRANULARITY: float = 0.1
MIN_SAMPLES_FOR_BEST: int = 3
HISTORY_CAP: int = 120
#: Per-apply mutation clamp and axis budget (Node v2 mutation rules).
MUTATE_DELTA_CLAMP: float = 0.2
MUTATE_MAX_AXES: int = 2
#: Natural-selection nudge parameters.
NUDGE_CLIP: float = 0.1
NUDGE_MIN_DIFF: float = 0.05

_STATS_FILENAME = "personality_stats.json"


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
    allowed = set(DEFAULT_PERSONALITY) | set(AXES_V2)
    clean = {k: max(0.0, min(1.0, float(v))) for k, v in state.items() if k in allowed}
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

    # Sprint 24.12 (enable_personality_v2): natural-selection nudge toward
    # best-known buckets after the heuristic adjustments.
    from evolver.gep.feature_flags import is_enabled

    if is_enabled("enable_personality_v2"):
        p = natural_nudge({**PERSONALITY_V2_DEFAULTS, **p})

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


# ---------------------------------------------------------------------------
# Sprint 24.12 (enable_personality_v2): five-axis vector, bucketed outcome
# statistics (Laplace blend), natural-selection nudge, bounded mutations,
# force pivot — Node v2 personality/{schema,stats,evolveOps}.d.ts semantics.
# ---------------------------------------------------------------------------


def _stats_path() -> Path:
    return get_evolver_settings_dir() / _STATS_FILENAME


def bucket_key(value: float) -> float:
    """Snap an axis value onto the 0.1 bucket grid."""
    return round(round(clamp(value) / BUCKET_GRANULARITY) * BUCKET_GRANULARITY, 1)


def load_personality_v2() -> dict[str, float]:
    """Five-axis personality; persisted values win, v2 defaults fill gaps."""
    path = _personality_path()
    state = dict(PERSONALITY_V2_DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for axis in AXES_V2:
                if isinstance(data.get(axis), (int, float)):
                    state[axis] = clamp(float(data[axis]))
    except (OSError, json.JSONDecodeError):
        pass
    return state


def _load_axis_stats() -> dict[str, Any]:
    try:
        raw = json.loads(_stats_path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_axis_stats(stats: dict[str, Any]) -> None:
    path = _stats_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(stats, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def record_axis_outcome(axis: str, value: float, score: float) -> None:
    """Attribute one outcome to the bucket this axis value maps to.

    Keeps per-bucket Laplace inputs and a bounded recent history (cap 120).
    """
    stats = _load_axis_stats()
    axis_stats = stats.setdefault(axis, {"buckets": {}, "history": []})
    buckets: dict[str, dict[str, float]] = axis_stats.setdefault("buckets", {})
    row = buckets.setdefault(
        str(bucket_key(value)), {"successes": 0.0, "total": 0.0, "score_sum": 0.0}
    )
    row["total"] += 1
    row["score_sum"] += clamp(score)
    if score >= 0.5:
        row["successes"] += 1

    history: list[Any] = axis_stats.setdefault("history", [])
    history.append({"bucket": bucket_key(value), "score": clamp(score)})
    del history[:-HISTORY_CAP]
    _save_axis_stats(stats)


def bucket_score(axis: str, bucket: float) -> tuple[float, int] | None:
    """Laplace-blended bucket quality: ``0.75*(s+1)/(n+2) + 0.25*avg``.

    The avg term's weight saturates at 8 total samples. Returns ``None``
    for unknown buckets.
    """
    axis_stats = _load_axis_stats().get(axis) or {}
    row = (axis_stats.get("buckets") or {}).get(str(bucket))
    if not row or not row.get("total"):
        return None
    total = int(row["total"])
    laplace = (row["successes"] + 1) / (total + 2)
    avg = row["score_sum"] / total
    blended = 0.75 * laplace + 0.25 * avg * min(1.0, total / 8)
    return round(blended, 6), total


def best_bucket(axis: str) -> float | None:
    """Best-known bucket for *axis*; needs MIN_SAMPLES_FOR_BEST evidence."""
    axis_stats = _load_axis_stats().get(axis) or {}
    best: tuple[float, int] | None = None
    best_value: float | None = None
    for raw in axis_stats.get("buckets") or {}:
        try:
            bucket = float(raw)
        except ValueError:
            continue
        scored = bucket_score(axis, bucket)
        if scored is None:
            continue
        score, total = scored
        if total < MIN_SAMPLES_FOR_BEST:
            continue
        if best is None or score > best[0]:
            best = (score, total)
            best_value = bucket
    return best_value


def natural_nudge(state: dict[str, float]) -> dict[str, float]:
    """Nudge each axis toward its best-known bucket (clip, min-diff)."""
    nudged = dict(state)
    for axis in AXES_V2:
        if axis not in nudged:
            continue
        target = best_bucket(axis)
        if target is None:
            continue
        diff = target - nudged[axis]
        if abs(diff) < NUDGE_MIN_DIFF:
            continue
        step = max(-NUDGE_CLIP, min(NUDGE_CLIP, diff))
        nudged[axis] = round(clamp(nudged[axis] + step), 4)
    return nudged


def mutate_personality_v2(state: dict[str, float], deltas: dict[str, float]) -> dict[str, float]:
    """Apply bounded drift: +/- clamp per axis, at most MUTATE_MAX_AXES axes."""
    mutated = dict(state)
    applied = 0
    for axis, delta in deltas.items():
        if axis not in mutated or applied >= MUTATE_MAX_AXES:
            continue
        bounded = max(-MUTATE_DELTA_CLAMP, min(MUTATE_DELTA_CLAMP, float(delta)))
        if bounded == 0.0:
            continue
        mutated[axis] = round(clamp(mutated[axis] + bounded), 4)
        applied += 1
    return mutated


def force_pivot(
    state: dict[str, float] | None = None, *, strength: str = "suggested"
) -> dict[str, float]:
    """Pivot adjustments (Node v2): creativity/risk bumps by strength."""
    p = dict(state) if state else load_personality()
    creativity_bump = 0.2 if strength == "required" else 0.15
    risk_bump = 0.15 if strength == "required" else 0.1
    p["creativity"] = clamp(p.get("creativity", 0.35) + creativity_bump)
    p["risk_tolerance"] = clamp(p.get("risk_tolerance", 0.4) + risk_bump)
    return p


__all__ = [
    "AXES_V2",
    "BUCKET_GRANULARITY",
    "DEFAULT_PERSONALITY",
    "HISTORY_CAP",
    "MIN_SAMPLES_FOR_BEST",
    "MUTATE_DELTA_CLAMP",
    "MUTATE_MAX_AXES",
    "PERSONALITY_V2_DEFAULTS",
    "adapt_personality",
    "best_bucket",
    "bucket_key",
    "bucket_score",
    "clamp",
    "force_pivot",
    "is_conservative_personality",
    "is_high_risk_personality",
    "load_personality",
    "load_personality_v2",
    "mutate_personality_v2",
    "natural_nudge",
    "personality_to_strategy_bias",
    "record_axis_outcome",
    "save_personality",
]
