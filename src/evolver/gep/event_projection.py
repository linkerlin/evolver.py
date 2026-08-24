"""Event projection — derived views rebuilt by replaying the event log.

Concept harvest from Node v2 ``events/projectors.js`` + ``replayer.js``
(behavioral re-implementation; no code copied). The root ``events.jsonl``
log stays the single source of truth: every view in this module is a pure
function of the event sequence, so a rebuild is always safe and side
effects (mutable state sidecars polluting fingerprints — the Sprint 23
soak finding) are structurally impossible.

Views:
- ``gene_outcomes``     per-gene attempt/success/score tallies (UCB1 feed)
- ``scored_categories`` ordered (category, score) pairs from EvolutionEvents
                        (operator-bandit window source, exact parity with
                        the previous inline scan in ``mutation.py``)
- ``category_totals``   full-history aggregate of the above
- ``cycle_timeline``    per-run stage timeline (see ``cycle_state_machine``)

Sprint 24.1 (演进方案.md §9 概念收割 #3). Flag: ``enable_event_projection``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from evolver.gep.cycle_state_machine import build_cycle_timeline

logger = logging.getLogger(__name__)

PROJECTIONS_FILENAME = "projections.json"
SCHEMA_VERSION = 1


def project_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Replay *events* and return all derived views (pure function)."""
    gene_outcomes: dict[str, dict[str, float]] = {}
    scored_categories: list[dict[str, Any]] = []

    for evt in events:
        if evt.get("type") != "EvolutionEvent":
            continue
        outcome = evt.get("outcome") or {}
        score = outcome.get("score")
        numeric_score = score if isinstance(score, (int, float)) else None

        gene_id = evt.get("gene_id")
        if isinstance(gene_id, str) and gene_id:
            row = gene_outcomes.setdefault(
                gene_id, {"attempts": 0.0, "successes": 0.0, "failures": 0.0, "score_sum": 0.0}
            )
            row["attempts"] += 1
            if str(outcome.get("status", "")).lower() == "success":
                row["successes"] += 1
            else:
                row["failures"] += 1
            if numeric_score is not None:
                row["score_sum"] += float(numeric_score)

        mutation = evt.get("mutation") or {}
        category = mutation.get("category")
        # Filter mirrors mutation._category_stats exactly (valid category +
        # numeric score), preserving event order so any window slice is
        # byte-equivalent with the historical inline scan.
        if category and isinstance(score, (int, float)):
            scored_categories.append({"category": category, "score": float(score)})

    category_totals: dict[str, dict[str, float]] = {}
    for pair in scored_categories:
        row = category_totals.setdefault(pair["category"], {"attempts": 0.0, "score_sum": 0.0})
        row["attempts"] += 1
        row["score_sum"] += pair["score"]

    return {
        "schema_version": SCHEMA_VERSION,
        "event_count": len(events),
        "gene_outcomes": gene_outcomes,
        "scored_categories": scored_categories,
        "category_totals": category_totals,
        "cycle_timeline": build_cycle_timeline(events),
    }


def projections_path() -> Path:
    """Return ``<GEP_ASSETS_DIR>/projections.json``."""
    from evolver.gep.asset_store import events_path

    return events_path().parent / PROJECTIONS_FILENAME


def rebuild_projections() -> dict[str, Any]:
    """Read the full event log, rebuild views, atomically persist them."""
    from evolver.gep.asset_store import atomic_write_json, read_all_events

    views = project_events(read_all_events())
    atomic_write_json(projections_path(), views)
    logger.info("[Projection] rebuilt views from %s event(s)", views["event_count"])
    return views


def load_projections() -> dict[str, Any] | None:
    """Load persisted projections, or ``None`` when absent/corrupt."""
    path = projections_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) and raw.get("schema_version") == SCHEMA_VERSION else None


def scored_category_window(window: int = 50) -> dict[str, dict[str, float]]:
    """Operator-bandit stats over the last *window* scored events.

    Replay-derived equivalent of the pre-projection inline scan in
    ``mutation._category_stats`` — same filter, same global window,
    same output shape.
    """
    from evolver.gep.asset_store import read_all_events

    tail = project_events(read_all_events())["scored_categories"][-window:]
    stats: dict[str, dict[str, float]] = {}
    for pair in tail:
        row = stats.setdefault(str(pair["category"]), {"attempts": 0.0, "score_sum": 0.0})
        row["attempts"] += 1
        row["score_sum"] += float(pair["score"])
    return stats


__all__ = [
    "PROJECTIONS_FILENAME",
    "SCHEMA_VERSION",
    "load_projections",
    "project_events",
    "projections_path",
    "rebuild_projections",
    "scored_category_window",
]
