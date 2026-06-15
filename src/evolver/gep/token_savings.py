"""Token savings tracker — estimate and report evolution-driven cost reductions.

Equivalent to ``evolver/src/gep/tokenSavings.js`` + ``savingsCore.js``.

Estimates the token/cost savings from using evolved genes vs. a baseline
(no-evolution average). Produces monthly reports in Markdown.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

#: Default model pricing (USD per 1M tokens). Override via env.
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
    "claude-3-7-sonnet": {"input": 3.0, "output": 15.0},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6},
    "gemini-2.0-flash": {"input": 0.1, "output": 0.4},
}


def get_model_pricing(model: str) -> dict[str, float]:
    """Return per-1M-token pricing for *model*, or a default."""
    for prefix, pricing in _MODEL_PRICING.items():
        if model.startswith(prefix):
            return pricing
    return {"input": 3.0, "output": 15.0}


def compute_savings(
    baseline_tokens: int,
    actual_tokens: int,
    model: str = "claude-3-5-sonnet",
) -> dict[str, Any]:
    """Compute token and cost savings for a single evolution cycle.

    Parameters:
        baseline_tokens: Average tokens without evolution.
        actual_tokens: Actual tokens consumed with evolution.
        model: Model name for pricing lookup.
    """
    saved_tokens = max(0, baseline_tokens - actual_tokens)
    pricing = get_model_pricing(model)
    # Assume 70% input, 30% output split for estimation.
    saved_cost = (saved_tokens * 0.7 * pricing["input"] / 1_000_000) + (
        saved_tokens * 0.3 * pricing["output"] / 1_000_000
    )
    return {
        "baseline_tokens": baseline_tokens,
        "actual_tokens": actual_tokens,
        "saved_tokens": saved_tokens,
        "saved_cost_usd": round(saved_cost, 4),
        "model": model,
    }


class SavingsTracker:
    """Accumulate token savings across evolution cycles."""

    def __init__(self, store_path: Path | None = None) -> None:
        self._store_path = store_path
        self._entries: list[dict[str, Any]] = []
        if store_path and store_path.exists():
            try:
                data = json.loads(store_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._entries = data
            except (json.JSONDecodeError, OSError):
                pass

    def record(self, baseline: int, actual: int, model: str = "") -> dict[str, Any]:
        model = model or "claude-3-5-sonnet"
        entry = compute_savings(baseline, actual, model)
        entry["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._entries.append(entry)
        self._save()
        return entry

    def get_summary(self) -> dict[str, Any]:
        total_saved = sum(e["saved_tokens"] for e in self._entries)
        total_cost = sum(e["saved_cost_usd"] for e in self._entries)
        return {
            "cycles": len(self._entries),
            "total_saved_tokens": total_saved,
            "total_saved_cost_usd": round(total_cost, 2),
        }

    def generate_report(self) -> str:
        """Generate a Markdown savings report."""
        summary = self.get_summary()
        lines = [
            "# Token Savings Report",
            f"\nGenerated: {time.strftime('%Y-%m-%d %H:%M')}",
            "\n## Summary\n",
            f"- Evolution cycles: **{summary['cycles']}**",
            f"- Total tokens saved: **{summary['total_saved_tokens']:,}**",
            f"- Estimated cost saved: **${summary['total_saved_cost_usd']:.2f}**",
        ]
        if self._entries:
            lines.append("\n## Recent Entries\n")
            lines.append("| Date | Model | Baseline | Actual | Saved | Cost |")
            lines.append("|------|-------|----------|--------|-------|------|")
            for e in self._entries[-10:]:
                lines.append(
                    f"| {e.get('timestamp', '')[:10]} | {e['model']} "
                    f"| {e['baseline_tokens']:,} | {e['actual_tokens']:,} "
                    f"| {e['saved_tokens']:,} | ${e['saved_cost_usd']:.4f} |"
                )
        return "\n".join(lines)

    def _save(self) -> None:
        if self._store_path:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            self._store_path.write_text(
                json.dumps(self._entries[-500:], indent=2), encoding="utf-8"
            )


__all__ = ["SavingsTracker", "compute_savings", "get_model_pricing"]
