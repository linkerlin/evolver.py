"""Shared memory filtering for adapter runtime scripts.

Equivalent to ``evolver/src/adapters/scripts/_memoryFiltering.js``.

Two functions:
  - :func:`filter_relevant_outcomes` — filter a pre-read list of entries
    (mirrors ``filterRelevantOutcomes`` in the Node reference).
  - :func:`filter_relevant_memories` — read and filter from the graph file
    (Python-original convenience wrapper).
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_MIN_SCORE = 0.5
DEFAULT_MAX_AGE_S = 7 * 24 * 60 * 60  # 7 days
DEFAULT_MAX_OUTCOMES = 3


def filter_relevant_outcomes(
    entries: list[dict[str, Any]],
    *,
    min_score: float = DEFAULT_MIN_SCORE,
    max_age_s: float = DEFAULT_MAX_AGE_S,
    max_outcomes: int = DEFAULT_MAX_OUTCOMES,
) -> list[dict[str, Any]]:
    """Filter evolution memory outcomes to reduce noise.

    Mirrors ``filterRelevantOutcomes`` in ``_memoryFiltering.js``:
      - Keep only ``success`` outcomes (failed ones have no learning value).
      - Drop low-confidence outcomes (score < *min_score*).
      - Enforce a time bound (older than *max_age_s* dropped).
      - Limit to the *max_outcomes* most recent.
    """
    now = time.time()
    kept: list[dict[str, Any]] = []
    for entry in entries:
        outcome = entry.get("outcome")
        if not isinstance(outcome, dict) or outcome.get("status") != "success":
            continue
        score = outcome.get("score", 0)
        if not isinstance(score, (int, float)) or score < min_score:
            continue
        ts_val = entry.get("timestamp", "")
        ts = 0.0
        if isinstance(ts_val, str) and ts_val:
            try:
                ts = datetime.fromisoformat(ts_val.replace("Z", "+00:00")).timestamp()
            except ValueError:
                ts = 0.0
        if ts and now - ts > max_age_s:
            continue
        kept.append(entry)
    return kept[-max_outcomes:] if max_outcomes > 0 else kept


def filter_relevant_memories(
    *,
    workspace: Path | None = None,
    scope: str = "workspace",
    limit: int = 5,
    min_score: float = 0.0,
) -> list[dict[str, Any]]:
    """Read the memory graph and return the most relevant memories.

    When *workspace* is provided, only entries matching the workspace dir
    (via ``cwd`` tag) are considered. Otherwise all entries are scored.
    """
    try:
        from evolver.gep.paths import get_memory_dir  # noqa: PLC0415
    except ImportError:
        return []

    memory_dir = get_memory_dir()
    graph_file = memory_dir / "memory_graph.jsonl"
    if not graph_file.exists():
        return []

    workspace_str = str(workspace) if workspace else None

    entries: list[dict[str, Any]] = []
    try:
        with open(graph_file, encoding="utf-8") as f:
            for raw_line in f:
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    if workspace_str:
                        entry_cwd = record.get("cwd", "")
                        if entry_cwd and str(entry_cwd) != workspace_str:
                            continue
                    entries.append(record)
    except OSError:
        return []

    now = time.time()
    scored: list[tuple[float, dict[str, Any]]] = []
    for rec in entries:
        ts = rec.get("ts", 0)
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            except ValueError:
                ts = 0
        age_days = (now - ts) / 86400 if ts else 0
        decay = 0.5 ** (age_days / 7)  # half-life 7 days
        base_score = rec.get("score", 0.5)
        score = base_score * decay
        if score >= min_score:
            scored.append((score, rec))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "signal": rec.get("signal", ""),
            "outcome": rec.get("outcome", ""),
            "score": round(score, 3),
            "ts": rec.get("ts", ""),
        }
        for score, rec in scored[:limit]
    ]


__all__ = [
    "DEFAULT_MAX_AGE_S",
    "DEFAULT_MAX_OUTCOMES",
    "DEFAULT_MIN_SCORE",
    "filter_relevant_memories",
    "filter_relevant_outcomes",
]
