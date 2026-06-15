"""Memory graph adapter — advanced query interface over the memory graph.

Equivalent to ``evolver/src/gep/memoryGraphAdapter.js``.

Provides higher-level query methods on top of ``memory_graph.py``: success
trajectory tracing, failure pattern clustering, and fuzzy signal matching.
The base ``memory_graph.py`` handles JSONL storage and key-based lookup;
this adapter adds analytical queries used by reflection and the WebUI.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def query_by_signal(
    entries: list[dict[str, Any]],
    signal_key: str,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return entries whose signals list contains *signal_key*."""
    result = [
        e for e in entries if signal_key in e.get("signals", [])
    ]
    return result[-limit:]


def query_by_outcome(
    entries: list[dict[str, Any]],
    status: str = "success",
    *,
    min_score: float = 0.0,
) -> list[dict[str, Any]]:
    """Return entries whose outcome status matches and score >= *min_score*."""
    result: list[dict[str, Any]] = []
    for e in entries:
        outcome = e.get("outcome")
        if not isinstance(outcome, dict):
            continue
        if outcome.get("status") == status:
            score = outcome.get("score", 0)
            if isinstance(score, (int, float)) and score >= min_score:
                result.append(e)
    return result


def get_success_trajectory(
    entries: list[dict[str, Any]],
    signal_key: str,
) -> list[dict[str, Any]]:
    """Trace the success path for a signal: chronological list of successful entries."""
    matches = query_by_signal(entries, signal_key)
    return [e for e in matches if _is_success(e)]


def get_failure_pattern(
    entries: list[dict[str, Any]],
    signal_key: str,
) -> dict[str, Any]:
    """Cluster failure modes for a signal into a pattern summary."""
    matches = query_by_signal(entries, signal_key)
    failures = [e for e in matches if not _is_success(e)]
    notes: list[str] = []
    for f in failures:
        outcome = f.get("outcome", {})
        if isinstance(outcome, dict):
            note = outcome.get("note", "")
            if note:
                notes.append(note)

    # Cluster by note similarity (simple prefix grouping).
    clusters: dict[str, int] = defaultdict(int)
    for note in notes:
        prefix = note[:50] if note else "(no note)"
        clusters[prefix] += 1

    return {
        "signal": signal_key,
        "total_failures": len(failures),
        "total_entries": len(matches),
        "failure_rate": len(failures) / max(len(matches), 1),
        "common_notes": dict(sorted(clusters.items(), key=lambda x: -x[1])[:5]),
    }


def _is_success(entry: dict[str, Any]) -> bool:
    outcome = entry.get("outcome")
    return isinstance(outcome, dict) and outcome.get("status") == "success"


def fuzzy_signal_match(
    entries: list[dict[str, Any]],
    query: str,
    *,
    max_distance: int = 3,
) -> list[dict[str, Any]]:
    """Match entries whose signals are within Levenshtein distance of *query*."""
    result: list[dict[str, Any]] = []
    for e in entries:
        for sig in e.get("signals", []):
            if _levenshtein(query.lower(), sig.lower()) <= max_distance:
                result.append(e)
                break
    return result


def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein edit distance (iterative, O(n*m))."""
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


__all__ = [
    "fuzzy_signal_match",
    "get_failure_pattern",
    "get_success_trajectory",
    "query_by_outcome",
    "query_by_signal",
]
