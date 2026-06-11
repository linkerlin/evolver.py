"""Recall injector — surface past successful strategies into the GEP prompt.

Equivalent to Node's ``evolver/src/gep/recallInject.js``.

Scans the memory graph for historical events that match the current
signal fingerprint. When a strong match is found, the corresponding
successful mutation (or learned rule) is injected into the GEP
context as a *recall* hint.

Matching strategy
-----------------
1. Compute a signal fingerprint (ordered list of keywords).
2. Search memory graph for ``attempt`` events with ``outcome=success``.
3. Score each by Jaccard similarity between the attempt's signal
   snapshot and the current fingerprint.
4. Return top-*k* matches as formatted recall strings.

Design notes
------------
* Offline — reads local JSONL only.
* Deterministic — same signals → same recalls.
* Respects the ``enable_recall_inject`` feature flag.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evolver.gep.feature_flags import is_enabled
from evolver.gep.memory_graph import get_memory_graph_path, try_read_memory_graph_events

logger = logging.getLogger(__name__)

# Default number of recall items to inject
DEFAULT_TOP_K = 3
# Minimum Jaccard similarity to consider a match
MIN_SIMILARITY = 0.3


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class RecallMatch:
    event_id: str
    similarity: float
    signals: list[str]
    mutation_summary: str
    outcome: str


# ---------------------------------------------------------------------------
# Similarity
# ---------------------------------------------------------------------------


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two sets."""
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _extract_keywords(text: str) -> set[str]:
    """Extract lowercase alphanumeric keywords from *text*."""
    return set(
        w.lower()
        for w in text.split()
        if w.isalnum() and len(w) > 2
    )


def _signal_fingerprint(signals: list[str]) -> set[str]:
    """Build a keyword set from a list of signal strings."""
    keywords: set[str] = set()
    for s in signals:
        keywords.update(_extract_keywords(s))
    return keywords


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def _find_successful_attempts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter events to successful attempts with signal snapshots."""
    results: list[dict[str, Any]] = []
    for ev in events:
        if ev.get("type") != "attempt":
            continue
        outcome = ev.get("outcome", "").lower()
        if "success" not in outcome and "pass" not in outcome:
            continue
        signals = ev.get("signals_snapshot") or ev.get("signals", [])
        if not signals:
            continue
        results.append(ev)
    return results


def _score_match(event: dict[str, Any], current_keywords: set[str]) -> float:
    """Return Jaccard similarity between *event* signals and *current_keywords*."""
    signals = event.get("signals_snapshot") or event.get("signals", [])
    event_keywords = _signal_fingerprint(signals)
    return _jaccard(event_keywords, current_keywords)


def search_recalls(
    current_signals: list[str],
    *,
    events: list[dict[str, Any]] | None = None,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = MIN_SIMILARITY,
) -> list[RecallMatch]:
    """Search memory for successful attempts similar to *current_signals*.

    Returns a list of :class:`RecallMatch` sorted by similarity desc.
    """
    if not is_enabled("enable_recall_inject"):
        return []

    if events is None:
        events = try_read_memory_graph_events()

    candidates = _find_successful_attempts(events)
    current_keywords = _signal_fingerprint(current_signals)

    matches: list[RecallMatch] = []
    for ev in candidates:
        sim = _score_match(ev, current_keywords)
        if sim < min_similarity:
            continue
        signals = ev.get("signals_snapshot") or ev.get("signals", [])
        matches.append(
            RecallMatch(
                event_id=ev.get("event_id", "unknown"),
                similarity=sim,
                signals=signals,
                mutation_summary=ev.get("mutation_summary", ""),
                outcome=ev.get("outcome", ""),
            )
        )

    matches.sort(key=lambda m: m.similarity, reverse=True)
    return matches[:top_k]


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_recall_prompt(matches: list[RecallMatch]) -> str:
    """Format *matches* into a Markdown prompt block for the GEP."""
    if not matches:
        return ""
    lines = ["## Recall Hints (from past successes)", ""]
    for i, m in enumerate(matches, 1):
        lines.append(f"{i}. **Similarity {m.similarity:.0%}** — {m.mutation_summary or 'unknown mutation'}")
        lines.append(f"   - Signals: {', '.join(m.signals[:5])}")
        lines.append(f"   - Outcome: {m.outcome}")
        lines.append("")
    return "\n".join(lines)


def inject_recall(
    current_signals: list[str],
    *,
    events: list[dict[str, Any]] | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> str:
    """High-level helper: search + format.

    Returns a Markdown string ready to append to a GEP prompt.
    """
    matches = search_recalls(current_signals, events=events, top_k=top_k)
    return format_recall_prompt(matches)
