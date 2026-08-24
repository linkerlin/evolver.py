"""Trigger engine — WFQ scheduling, problem value model, daily budgets.

Concept harvest from Node v2 ``trigger/{wfq,valueModel,budget}.js``
(behavioral re-implementation; no code copied).

- :class:`WeightedFairQueue` — fair-pick queue with anti-starvation age
  boost: ``priority = weight + min(log2(1 + wait_minutes), 4)``.
- :func:`problem_value` — ``severity · reach_sat · strategic_fit ·
  (1 + novelty) / (1 + cost_est)`` where reach saturates at a fixed scale
  (30 occurrences) instead of normalizing to the biggest bucket.
- :class:`DailyBudget` — persisted per-day caps on cycles/tokens/patterns;
  auto-resets when the local date rolls over.

Sprint 24.4 (演进方案.md §9 概念收割 — trigger 经济学).
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Reach saturation point — deliberately a FIXED scale, not normalized to
#: the biggest observed bucket (Node v2 valueModel REACH_FULL_AT = 30).
REACH_FULL_AT: int = 30

#: Strategic fit for problems that carry no classification signal.
UNCLASSIFIED_STRATEGIC_FIT: float = 0.35

#: Anti-starvation age-boost ceiling (minutes → priority points).
MAX_AGE_BOOST: float = 4.0

BUDGET_FILENAME = "trigger_budget.json"


# ---------------------------------------------------------------------------
# Weighted fair queue
# ---------------------------------------------------------------------------


class WeightedFairQueue:
    """Fair-pick priority queue; enqueue dedups by id."""

    def __init__(self) -> None:
        self._items: dict[str, dict[str, float]] = {}

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, item_id: object) -> bool:
        return isinstance(item_id, str) and item_id in self._items

    def enqueue(self, item_id: str, weight: float = 1.0, *, now: float | None = None) -> bool:
        """Insert *item_id*; returns ``False`` when it was already queued."""
        if item_id in self._items:
            return False
        self._items[item_id] = {
            "weight": float(weight),
            "enqueued_at": now if now is not None else _now_s(),
        }
        return True

    def pick(self, *, now: float | None = None) -> str | None:
        """Pop the highest-priority id (weight + capped age boost)."""
        if not self._items:
            return None
        current = now if now is not None else _now_s()
        best_id: str | None = None
        best_priority = -math.inf
        for item_id, row in self._items.items():
            wait_minutes = max(0.0, (current - row["enqueued_at"]) / 60.0)
            age_boost = min(math.log2(1.0 + wait_minutes), MAX_AGE_BOOST)
            priority = row["weight"] + age_boost
            if priority > best_priority:
                best_priority = priority
                best_id = item_id
        assert best_id is not None
        del self._items[best_id]
        return best_id

    def peek_priorities(self, *, now: float | None = None) -> dict[str, float]:
        """Read-only view of current priorities (dashboards/tests)."""
        current = now if now is not None else _now_s()
        priorities: dict[str, float] = {}
        for item_id, row in self._items.items():
            wait_minutes = max(0.0, (current - row["enqueued_at"]) / 60.0)
            priorities[item_id] = row["weight"] + min(math.log2(1.0 + wait_minutes), MAX_AGE_BOOST)
        return priorities


def _now_s() -> float:
    import time

    return time.time()


# ---------------------------------------------------------------------------
# Problem value model
# ---------------------------------------------------------------------------


def problem_value(
    *,
    severity: float,
    reach_count: int,
    strategic_fit: float = UNCLASSIFIED_STRATEGIC_FIT,
    novelty: float = 0.0,
    cost_est: float = 1.0,
) -> float:
    """Score how much a problem pattern deserves an evolution cycle."""
    reach_sat = min(max(reach_count, 0) / REACH_FULL_AT, 1.0)
    denom = 1.0 + max(cost_est, 0.0)
    return (
        max(severity, 0.0) * reach_sat * max(strategic_fit, 0.0) * (1.0 + max(novelty, 0.0)) / denom
    )


# ---------------------------------------------------------------------------
# Daily budget
# ---------------------------------------------------------------------------


class DailyBudget:
    """Persisted per-day caps; auto-resets on local date rollover."""

    def __init__(
        self,
        *,
        path: Path | None = None,
        max_cycles_per_day: int | None = None,
        max_tokens_per_day: int | None = None,
        per_pattern_cap: int | None = None,
    ) -> None:
        self.path = path or (_budget_dir() / BUDGET_FILENAME)
        self.max_cycles = (
            max_cycles_per_day
            if max_cycles_per_day is not None
            else _env_int("EVOLVER_MAX_CYCLES_PER_DAY", 0)
        )
        self.max_tokens = (
            max_tokens_per_day
            if max_tokens_per_day is not None
            else _env_int("EVOLVER_MAX_TOKENS_PER_DAY", 0)
        )
        self.per_pattern_cap = (
            per_pattern_cap
            if per_pattern_cap is not None
            else _env_int("EVOLVER_PER_PATTERN_CAP_PER_DAY", 0)
        )
        self._state: dict[str, Any] = {"date": "", "cycles": 0, "tokens": 0, "patterns": {}}
        self._load()

    # -- persistence --------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._state = {
                    "date": str(raw.get("date", "")),
                    "cycles": int(raw.get("cycles", 0)),
                    "tokens": int(raw.get("tokens", 0)),
                    "patterns": {str(k): int(v) for k, v in (raw.get("patterns") or {}).items()},
                }
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        self._rollover()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._state, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.debug("[DailyBudget] persist failed: %s", exc)

    def _rollover(self) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if self._state["date"] != today:
            self._state = {"date": today, "cycles": 0, "tokens": 0, "patterns": {}}

    # -- decisions ----------------------------------------------------------

    def can_fire(self, *, tokens: int = 0, pattern: str | None = None) -> bool:
        """True when at least one more cycle fits all configured caps.

        A cap of ``0`` means unlimited for that dimension.
        """
        self._rollover()
        if self.max_cycles and self._state["cycles"] >= self.max_cycles:
            return False
        if self.max_tokens and self._state["tokens"] + tokens > self.max_tokens:
            return False
        if self.per_pattern_cap and pattern is not None:
            if self._state["patterns"].get(pattern, 0) >= self.per_pattern_cap:
                return False
        return True

    def consume(self, *, tokens: int = 0, pattern: str | None = None) -> None:
        self._rollover()
        self._state["cycles"] += 1
        self._state["tokens"] += max(0, tokens)
        if pattern is not None:
            patterns: dict[str, int] = self._state["patterns"]
            patterns[pattern] = patterns.get(pattern, 0) + 1
        self._save()

    def snapshot(self) -> dict[str, Any]:
        self._rollover()
        return dict(self._state)


def _budget_dir() -> Path:
    from evolver.gep.paths import get_evolution_dir

    return get_evolution_dir()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


__all__ = [
    "BUDGET_FILENAME",
    "MAX_AGE_BOOST",
    "REACH_FULL_AT",
    "UNCLASSIFIED_STRATEGIC_FIT",
    "DailyBudget",
    "WeightedFairQueue",
    "problem_value",
]
