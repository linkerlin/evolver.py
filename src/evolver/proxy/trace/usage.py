"""Token usage aggregator — accumulate and report token consumption.

Equivalent to ``evolver/src/proxy/trace/usage.js``.

Aggregates token usage across proxy requests, broken down by model and
upstream, for cost tracking and Hub reporting.
"""

from __future__ import annotations

import time
from typing import Any


class UsageAggregator:
    """Accumulate token usage by model and upstream."""

    def __init__(self) -> None:
        self._totals: dict[str, dict[str, int]] = {}
        self._requests: int = 0
        self._start_time: float = time.time()

    def record(
        self,
        model: str,
        upstream: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Record a single request's token usage."""
        key = f"{model}@{upstream}"
        bucket = self._totals.setdefault(
            key, {"input_tokens": 0, "output_tokens": 0, "requests": 0}
        )
        bucket["input_tokens"] += input_tokens
        bucket["output_tokens"] += output_tokens
        bucket["requests"] += 1
        self._requests += 1

    def get_summary(self) -> dict[str, Any]:
        """Return a summary of all recorded usage."""
        total_input = sum(b["input_tokens"] for b in self._totals.values())
        total_output = sum(b["output_tokens"] for b in self._totals.values())
        return {
            "total_requests": self._requests,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "uptime_s": round(time.time() - self._start_time, 1),
            "by_model": dict(self._totals),
        }

    def reset(self) -> None:
        """Clear all accumulated usage."""
        self._totals.clear()
        self._requests = 0
        self._start_time = time.time()


#: Module-level singleton for convenience.
_aggregator = UsageAggregator()


def get_aggregator() -> UsageAggregator:
    """Return the module-level usage aggregator singleton."""
    return _aggregator


__all__ = ["UsageAggregator", "get_aggregator"]
