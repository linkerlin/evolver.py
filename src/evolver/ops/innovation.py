"""Innovation tracker: measure and evaluate the success rate of innovation attempts.

Equivalent to evolver/src/ops/innovation.js.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from evolver.gep.paths import get_evolution_dir

INNOVATION_LOG_PATH_ENV = "EVOLVER_INNOVATION_LOG_PATH"


def _innovation_log_path() -> Path:
    env = __import__("os").environ.get(INNOVATION_LOG_PATH_ENV)
    if env:
        return Path(env)
    return get_evolution_dir() / "innovation_log.jsonl"


def _read_innovation_events(limit: int = 1_000) -> list[dict[str, Any]]:
    path = _innovation_log_path()
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                if len(events) >= limit:
                    break
    except OSError:
        return []
    return events


def _append_event(event: dict[str, Any]) -> None:
    path = _innovation_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def record_innovation_attempt(
    *,
    gene_id: str | None = None,
    strategy: str = "innovate",
    hypothesis: str = "",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Record the start of an innovation attempt."""
    event = {
        "type": "InnovationEvent",
        "kind": "attempt",
        "id": f"inv_{int(time.time() * 1000)}_{__import__('secrets').token_hex(4)}",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime())
        + f"{int((time.time() % 1) * 1000):03d}Z",
        "gene_id": gene_id,
        "strategy": strategy,
        "hypothesis": hypothesis,
        "run_id": run_id,
    }
    _append_event(event)
    return event


def record_innovation_outcome(
    *,
    attempt_id: str,
    gene_id: str | None = None,
    status: str,  # "success" | "failed" | "partial"
    score: float | None = None,
    capsule_id: str | None = None,
    note: str = "",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Record the outcome of an innovation attempt."""
    event = {
        "type": "InnovationEvent",
        "kind": "outcome",
        "id": f"inv_out_{int(time.time() * 1000)}_{__import__('secrets').token_hex(4)}",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime())
        + f"{int((time.time() % 1) * 1000):03d}Z",
        "attempt_id": attempt_id,
        "gene_id": gene_id,
        "status": status,
        "score": score,
        "capsule_id": capsule_id,
        "note": note,
        "run_id": run_id,
    }
    _append_event(event)
    return event


def compute_innovation_roi(
    *,
    window_days: int = 30,
    min_attempts: int = 3,
) -> dict[str, Any]:
    """Compute innovation ROI over a time window.

    ROI = successful_capsules / total_attempts
    """
    events = _read_innovation_events()
    cutoff = time.time() - window_days * 86400

    attempts = [
        e for e in events if e.get("kind") == "attempt" and _ts_to_epoch(e.get("ts", "")) >= cutoff
    ]
    outcomes = [
        e for e in events if e.get("kind") == "outcome" and _ts_to_epoch(e.get("ts", "")) >= cutoff
    ]

    total_attempts = len(attempts)
    if total_attempts < min_attempts:
        return {
            "roi": None,
            "total_attempts": total_attempts,
            "successful": 0,
            "failed": 0,
            "partial": 0,
            "capsules_created": 0,
            "insufficient_data": True,
            "window_days": window_days,
        }

    successful = sum(1 for o in outcomes if o.get("status") == "success")
    failed = sum(1 for o in outcomes if o.get("status") == "failed")
    partial = sum(1 for o in outcomes if o.get("status") == "partial")
    capsules_created = len({o.get("capsule_id") for o in outcomes if o.get("capsule_id")})

    roi = successful / total_attempts if total_attempts > 0 else 0.0

    # Per-strategy breakdown
    strategies: dict[str, dict[str, int]] = {}
    for a in attempts:
        s = a.get("strategy", "unknown")
        strategies.setdefault(s, {"attempts": 0, "successes": 0})
        strategies[s]["attempts"] += 1
    for o in outcomes:
        s = o.get("strategy", "unknown")
        strategies.setdefault(s, {"attempts": 0, "successes": 0})
        if o.get("status") == "success":
            strategies[s]["successes"] += 1

    return {
        "roi": round(roi, 4),
        "total_attempts": total_attempts,
        "successful": successful,
        "failed": failed,
        "partial": partial,
        "capsules_created": capsules_created,
        "insufficient_data": False,
        "window_days": window_days,
        "by_strategy": {
            k: {**v, "roi": round(v["successes"] / v["attempts"], 4) if v["attempts"] > 0 else 0.0}
            for k, v in strategies.items()
        },
    }


def _ts_to_epoch(ts: str) -> float:
    """Parse ISO timestamp to epoch seconds."""
    if not ts:
        return 0.0
    try:
        # Handle format 2026-01-01T12:00:00.123Z
        ts = ts.replace("Z", "+00:00")
        from datetime import datetime

        dt = datetime.fromisoformat(ts)
        return dt.timestamp()
    except Exception:
        return 0.0


def get_innovation_summary() -> dict[str, Any]:
    """High-level innovation summary for dashboard / CLI."""
    roi_7d = compute_innovation_roi(window_days=7, min_attempts=1)
    roi_30d = compute_innovation_roi(window_days=30, min_attempts=3)
    roi_90d = compute_innovation_roi(window_days=90, min_attempts=5)

    return {
        "last_7d": roi_7d,
        "last_30d": roi_30d,
        "last_90d": roi_90d,
        "recommendation": _recommendation(roi_30d),
    }


def _recommendation(roi_30d: dict[str, Any]) -> str:
    if roi_30d.get("insufficient_data"):
        return "insufficient_data"
    r = roi_30d.get("roi", 0.0)
    if r < 0.1:
        return "reduce_innovation_focus"
    if r < 0.3:
        return "increase_validation"
    if r < 0.5:
        return "steady_state"
    if r < 0.7:
        return "increase_innovation"
    return "double_down"


__all__ = [
    "compute_innovation_roi",
    "get_innovation_summary",
    "record_innovation_attempt",
    "record_innovation_outcome",
]
