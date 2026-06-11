"""Conversation distiller — compress dialogue history into memory summaries.

Equivalent to Node's ``evolver/src/gep/autoDistillConv.js``.

Reads the memory-graph event stream, groups events by time window,
and extracts key themes, decisions, and failures into compact
*distill* events that are appended back to the memory graph.

Design notes
------------
* Works entirely offline on the local JSONL event stream.
* Time windowing prevents runaway growth (default 1 h).
* Output is structured so that :mod:`recall_inject` can match it.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evolver.gep.memory_graph import get_memory_graph_path
from evolver.gep.paths import get_workspace_root

logger = logging.getLogger(__name__)

# Default look-back window (seconds)
DEFAULT_WINDOW_SECONDS = 3600


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class DistillSummary:
    window_start: float
    window_end: float
    themes: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0-1

    def to_event(self) -> dict[str, Any]:
        return {
            "type": "distill",
            "timestamp": time.time(),
            "window_start": self.window_start,
            "window_end": self.window_end,
            "themes": self.themes,
            "decisions": self.decisions,
            "failures": self.failures,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_events(path: Path | None = None, since: float = 0.0) -> list[dict[str, Any]]:
    """Read events from the memory graph JSONL since *since*."""
    p = path or get_memory_graph_path()
    if not p.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict) and obj.get("timestamp", 0) >= since:
                        events.append(obj)
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        logger.warning("[AutoDistillConv] Failed to read events: %s", exc)
    return events


def _extract_themes(events: list[dict[str, Any]]) -> list[str]:
    """Extract recurring themes from signal/hypothesis events."""
    themes: set[str] = set()
    for ev in events:
        typ = ev.get("type", "")
        if typ == "signal":
            desc = ev.get("description", "")
            if desc:
                themes.add(desc)
        elif typ == "hypothesis":
            h = ev.get("hypothesis", "")
            if h:
                themes.add(h)
        elif typ == "distill":
            themes.update(ev.get("themes", []))
    # Deduplicate by normalising whitespace
    return sorted({t.strip() for t in themes if t.strip()})


def _extract_decisions(events: list[dict[str, Any]]) -> list[str]:
    """Extract explicit decisions (attempts with outcomes)."""
    decisions: list[str] = []
    for ev in events:
        if ev.get("type") == "attempt":
            outcome = ev.get("outcome", "")
            if outcome:
                decisions.append(outcome)
    return decisions


def _extract_failures(events: list[dict[str, Any]]) -> list[str]:
    """Extract failures (attempts with error or negative outcome)."""
    failures: list[str] = []
    for ev in events:
        if ev.get("type") == "attempt":
            error = ev.get("error", "")
            if error:
                failures.append(error)
            outcome = ev.get("outcome", "")
            if "fail" in outcome.lower() or "error" in outcome.lower():
                failures.append(outcome)
    # Deduplicate
    return sorted(set(failures))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def distill_window(
    *,
    events: list[dict[str, Any]] | None = None,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    now: float | None = None,
) -> DistillSummary | None:
    """Distill a single time window of events.

    If *events* is omitted, reads from the memory graph.
    Returns ``None`` if no events are found.
    """
    t = now if now is not None else time.time()
    start = t - window_seconds
    if events is None:
        events = _read_events(since=start)
    else:
        events = [e for e in events if e.get("timestamp", 0) >= start]

    if not events:
        return None

    themes = _extract_themes(events)
    decisions = _extract_decisions(events)
    failures = _extract_failures(events)

    # Simple confidence heuristic: more unique themes → higher confidence
    confidence = min(1.0, len(themes) / 10.0 + len(decisions) / 20.0)

    return DistillSummary(
        window_start=start,
        window_end=t,
        themes=themes,
        decisions=decisions,
        failures=failures,
        confidence=confidence,
    )


def distill_and_append(
    *,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    path: Path | None = None,
) -> DistillSummary | None:
    """Distill the recent window and append the result to the memory graph.

    Returns the summary, or ``None`` if nothing to distill.
    """
    p = path or get_memory_graph_path()
    now = time.time()
    events = _read_events(path=p, since=now - window_seconds)
    summary = distill_window(events=events, window_seconds=window_seconds, now=now)
    if summary is None:
        return None
    event = summary.to_event()
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        logger.info(
            "[AutoDistillConv] Appended distill event (themes=%d, decisions=%d, failures=%d)",
            len(summary.themes),
            len(summary.decisions),
            len(summary.failures),
        )
    except OSError as exc:
        logger.warning("[AutoDistillConv] Failed to append distill event: %s", exc)
    return summary
