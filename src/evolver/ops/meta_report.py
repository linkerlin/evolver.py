"""Improvement-mechanism telemetry (RSI P0-2, arXiv:2609.11873 §3.6.5).

Read-only aggregation over ``events.jsonl`` + ``feedback.jsonl`` answering the
question the soak report never asks: **does the engine's improvement machinery
get better at improving?** (structural vs effective L5 — HGM's distinction
between current performance and the ability to produce better successors.)

Panels (Table-8 of the paper, adapted to available telemetry):
- adaptivity   : accepted/rejected trajectory across rolling windows
- retention    : recurrence of the trigger signals a landed gene addressed
- transfer     : landed genes re-appearing under different signal families
- efficiency   : rounds per validated gain (cost proxies where recorded)
- stability    : rollbacks (failed events) + degraded feedback counts
- meta_recursion : structural-L5 audit rows — mutations that touched the
  improvement machinery itself, with their descendants' outcomes

Descendant quality: per landed gene, the K rounds after landing — did its
trigger signals recur (unresolved) or vanish (resolved)?

Honesty notes: file-level attribution parses ``diff --git`` headers from the
truncated ``diff_snapshot`` (first ~2k chars) — a heuristic audit, not a
complete diff registry; cost accounting is count-based until per-stage
durations land on events. No Node.js equivalent; self-research addition.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from evolver.config import ANCHOR_TRIGGER_SURFACES
from evolver.gep.git_ops import normalize_rel_path

# Surfaces whose mutation means "the improvement machinery edited itself"
# (structural-L5). Verifier surfaces (anchor triggers) plus the evolution
# engine's own selector/mutation/prompt/pipeline code.
META_MECHANISM_SURFACES: tuple[str, ...] = (
    *ANCHOR_TRIGGER_SURFACES,
    "src/evolver/gep/adaptive.py",
    "src/evolver/gep/mutation.py",
    "src/evolver/gep/prompt.py",
    "src/evolver/gep/selector.py",
    "src/evolver/evolve/",
)

_DESCENDANT_WINDOW_EVENTS = 5
_DIFF_FILE_RE = re.compile(r"^diff --git a/(\S+) b/", re.MULTILINE)


def _event_ts(e: dict[str, Any]) -> str:
    return str(e.get("timestamp") or "")


def _files_touched(e: dict[str, Any]) -> list[str]:
    """Heuristic file list from the (truncated) diff snapshot headers."""
    blob = str(e.get("diff_snapshot") or "") + "\n" + str(e.get("novelty_fingerprint") or "")
    return [normalize_rel_path(m) for m in _DIFF_FILE_RE.findall(blob)]


def _landed_genes(e: dict[str, Any]) -> list[str]:
    m = e.get("mutation") or {}
    ids = m.get("landed_gene_ids") or ([] if not m.get("landed_gene_id") else [m["landed_gene_id"]])
    return [str(g) for g in ids if g]


def _trigger_signals(e: dict[str, Any]) -> set[str]:
    sig = e.get("signals") or (e.get("mutation") or {}).get("trigger_signals") or []
    return {str(s) for s in sig}


def _mechanism_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Structural-L5 audit: mutations on the improvement machinery with the
    success rate of the rounds that followed them."""
    rows: list[dict[str, Any]] = []
    for idx, e in enumerate(events):
        touched = [
            f
            for f in _files_touched(e)
            if any(f == p or f.startswith(p) for p in META_MECHANISM_SURFACES)
        ]
        if not touched:
            continue
        descendants = events[idx + 1 : idx + 1 + _DESCENDANT_WINDOW_EVENTS]
        desc_outcomes = [str((d.get("outcome") or {}).get("status") or "") for d in descendants]
        rows.append(
            {
                "event_id": e.get("id"),
                "timestamp": _event_ts(e),
                "landed_genes": _landed_genes(e),
                "outcome": (e.get("outcome") or {}).get("status"),
                "mechanism_files": sorted(set(touched))[:6],
                "descendants": len(descendants),
                "descendant_success_rate": (
                    round(sum(1 for o in desc_outcomes if o == "success") / len(desc_outcomes), 3)
                    if desc_outcomes
                    else None
                ),
                "anchor_result": (e.get("anchor_result") or None),
            }
        )
    return rows


def _descendant_quality(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per landed gene: did its trigger signals recur in the following rounds?"""
    rows: list[dict[str, Any]] = []
    for idx, e in enumerate(events):
        landed = _landed_genes(e)
        if not landed or (e.get("outcome") or {}).get("status") != "success":
            continue
        triggers = _trigger_signals(e)
        descendants = events[idx + 1 : idx + 1 + _DESCENDANT_WINDOW_EVENTS]
        recurred = sum(
            1
            for d in descendants
            if triggers
            and triggers & _trigger_signals(d)
            and (d.get("outcome") or {}).get("status") == "failed"
        )
        rows.append(
            {
                "landed_gene": landed[0],
                "event_id": e.get("id"),
                "trigger_signals": sorted(triggers)[:6],
                "descendants_observed": len(descendants),
                "signal_recurrence_in_failures": recurred,
                "resolved": len(descendants) > 0 and recurred == 0,
                "unknown": len(descendants) == 0,
            }
        )
    return rows


def build_meta_report(
    events: list[dict[str, Any]],
    feedback: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate the improvement-mechanism panel. Read-only."""
    feedback = feedback or []
    outcomes = [str((e.get("outcome") or {}).get("status") or "") for e in events]
    accepted = [i for i, o in enumerate(outcomes) if o == "success"]
    failed = [i for i, o in enumerate(outcomes) if o == "failed"]
    degraded = [
        f
        for f in feedback
        if str(f.get("success")) == "False" or (f.get("primary_score") or 1.0) < 0.5
    ]
    gains_traj: list[int] = []
    window = max(1, len(events) // 5) if events else 1
    for start in range(0, len(events), window):
        chunk = outcomes[start : start + window]
        gains_traj.append(sum(1 for o in chunk if o == "success"))

    # transfer: landed gene seen again under a different dominant signal head
    gene_signal_heads: dict[str, set[str]] = {}
    for e in events:
        for g in _landed_genes(e):
            heads = {s.split(":", 1)[0] for s in _trigger_signals(e)}
            gene_signal_heads.setdefault(g, set()).update(heads)
    transferred = {g: sorted(h) for g, h in gene_signal_heads.items() if len(h) > 1}

    rounds_per_gain = round(len(events) / len(accepted), 2) if accepted else None
    # Round-16: per-stage validation durations land on events as
    # validation_timing; convert to ms-per-validated-gain when present.
    timing_ms = [
        int((e.get("validation_timing") or {}).get("total_ms") or 0)
        for e in events
        if (e.get("validation_timing") or {}).get("total_ms")
    ]
    ms_per_gain = round(sum(timing_ms) / len(accepted)) if timing_ms and accepted else None
    dq = _descendant_quality(events)
    resolved = sum(1 for r in dq if r["resolved"])
    unknown = sum(1 for r in dq if r["unknown"])
    mechanism_rows = _mechanism_rows(events)

    return {
        "panel": {
            "adaptivity": {
                "events": len(events),
                "accepted": len(accepted),
                "failed": len(failed),
                "accepted_per_window": gains_traj,
            },
            "retention": {
                "landed_genes_tracked": len(dq),
                "signal_recurrence_free": resolved,
                "insufficient_descendants": unknown,
            },
            "transfer": {
                "genes_under_multiple_signal_families": len(transferred),
                "detail": transferred,
            },
            "efficiency": {
                "rounds_per_validated_gain": rounds_per_gain,
                "validation_ms_per_validated_gain": ms_per_gain,
                "timed_events": len(timing_ms),
                "note": (
                    "time-based when validation_timing present; else count-based"
                    if ms_per_gain is not None
                    else "count-based until validation_timing lands on events"
                ),
            },
            "stability": {
                "failed_events": len(failed),
                "degraded_feedback": len(degraded),
            },
            "meta_recursion": {
                "structural_l5_mutations": len(mechanism_rows),
            },
        },
        "mechanism_audit": mechanism_rows,
        "descendant_quality": dq,
    }


def load_feedback_events(evolution_dir: Path | None = None) -> list[dict[str, Any]]:
    """Best-effort load of feedback.jsonl (missing file → empty)."""
    from evolver.gep.paths import get_evolution_dir

    path = (evolution_dir or get_evolution_dir()) / "feedback.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


__all__ = [
    "META_MECHANISM_SURFACES",
    "build_meta_report",
    "load_feedback_events",
]
