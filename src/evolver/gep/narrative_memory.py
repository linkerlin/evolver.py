"""Narrative memory — compress evolution history into a readable narrative.

Equivalent to ``evolver/src/gep/narrativeMemory.js``.

Distinct from ``ops/narrative.py`` (which logs cycle events): this module
reads the full ``events.jsonl`` history and produces a compressed, human-
readable narrative of what the evolution system has learned — the "story"
of successes, failures, and recurring patterns. Used by the WebUI and the
session-start hook to give the agent a concise history.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def load_events(events_path: Path) -> list[dict[str, Any]]:
    """Load evolution events from a JSONL file."""
    if not events_path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        for raw_line in events_path.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                events.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return events


def build_narrative(events: list[dict[str, Any]], *, max_entries: int = 50) -> str:
    """Build a compressed narrative string from evolution events.

    Groups events by category (repair/optimize/innovate), summarizes the
    success rate, and lists the most common signals and genes.
    """
    if not events:
        return "[Evolution Narrative] No evolution events recorded yet."

    recent = events[-max_entries:]
    categories: Counter[str] = Counter()
    signals: Counter[str] = Counter()
    gene_ids: Counter[str] = Counter()
    successes = 0
    failures = 0

    for event in recent:
        cat = event.get("category", event.get("intent", "unknown"))
        categories[cat] += 1
        outcome = event.get("outcome", {})
        if isinstance(outcome, dict):
            status = outcome.get("status", "")
            if status == "success":
                successes += 1
            elif status == "failed":
                failures += 1
        for sig in event.get("signals", []):
            signals[sig] += 1
        gene_id = event.get("gene_id", "")
        if gene_id:
            gene_ids[gene_id] += 1

    total = len(recent)
    success_rate = (successes / total * 100) if total else 0

    lines = [
        f"[Evolution Narrative] {total} recent events "
        f"({success_rate:.0f}% success, {failures} failed).",
    ]

    if categories:
        cat_summary = ", ".join(f"{cat}: {n}" for cat, n in categories.most_common(5))
        lines.append(f"  By category: {cat_summary}")

    if signals:
        sig_summary = ", ".join(f"{s}({n})" for s, n in signals.most_common(5))
        lines.append(f"  Top signals: {sig_summary}")

    if gene_ids:
        gene_summary = ", ".join(f"{g}({n})" for g, n in gene_ids.most_common(3))
        lines.append(f"  Most used genes: {gene_summary}")

    return "\n".join(lines)


def get_narrative(events_path: Path | None = None) -> str:
    """Convenience: load events and build narrative in one call."""
    if events_path is None:
        from evolver.gep.paths import get_evolution_dir  # noqa: PLC0415

        events_path = get_evolution_dir() / "events.jsonl"
    return build_narrative(load_events(events_path))


__all__ = ["build_narrative", "get_narrative", "load_events"]
