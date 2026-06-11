"""Shared memory filtering for adapter runtime scripts."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def filter_relevant_memories(
    *,
    workspace: Path,
    scope: str = "workspace",
    limit: int = 5,
    min_score: float = 0.0,
) -> list[dict[str, Any]]:
    """Return the most relevant memories for the current context."""
    try:
        from evolver.gep.paths import get_memory_dir
    except ImportError:
        return []

    memory_dir = get_memory_dir()
    graph_file = memory_dir / "memory_graph.jsonl"
    if not graph_file.exists():
        return []

    entries: list[dict[str, Any]] = []
    try:
        with open(graph_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                entries.append(record)
    except OSError:
        return []

    # Time decay: newer memories score higher
    now = time.time()
    scored: list[tuple[float, dict[str, Any]]] = []
    for rec in entries:
        ts = rec.get("ts", 0)
        if isinstance(ts, str):
            try:
                from datetime import datetime

                ts = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
            except Exception:
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
