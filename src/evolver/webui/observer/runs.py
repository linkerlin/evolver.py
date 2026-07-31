"""Evolution run history for WebUI — multi-source aggregation + call-log correlation.

Behavioral port of the portable subset of ``evolver/src/webui/observer/runs.js``.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from evolver.gep.asset_call_log import read_call_log, reuse_attribution_summary
from evolver.webui.observer.jsonl import stream_jsonl
from evolver.webui.observer.redact import redact_text

# Runs with status=running older than this are reclassified abandoned.
_STUCK_THRESHOLD_MS = int(os.environ.get("EVOLVER_RUN_STUCK_THRESHOLD_MS", str(30 * 60 * 1000)))


def _ts(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        try:
            # ISO or numeric string
            if value.replace(".", "", 1).isdigit():
                return float(value)
            from datetime import datetime

            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            return 0.0
    return 0.0


def _belongs_to_run(entry: dict[str, Any], run_id: str) -> bool:
    return str(entry.get("run_id") or "") == str(run_id)


def runs_history(*, limit: int = 50, memory_dir: Path | None = None) -> dict[str, Any]:
    """Return run-level statistics enriched with asset reuse and token costs."""
    from evolver.gep.paths import get_memory_dir

    mem = memory_dir or get_memory_dir()
    events = list(stream_jsonl(mem / "events.jsonl"))

    cycles = [e for e in events if e.get("type") in ("cycle_end", "EvolutionEvent")]
    # Prefer cycle_end when present; fall back to EvolutionEvent success/fail
    cycle_ends = [e for e in events if e.get("type") == "cycle_end"]
    if cycle_ends:
        cycles = cycle_ends

    total = len(cycles)
    successes = sum(
        1
        for c in cycles
        if c.get("outcome") == "success"
        or (isinstance(c.get("outcome"), dict) and c["outcome"].get("status") == "success")
    )
    failures = total - successes
    rate = successes / total if total else 0.0

    recent = cycles[-limit:]
    recent.reverse()
    run_ids = [c.get("run_id") for c in recent if c.get("run_id")]

    call_log_by_run: dict[str, list[dict[str, Any]]] = {}
    for rid in run_ids:
        entries = read_call_log({"run_id": rid})
        if entries:
            call_log_by_run[str(rid)] = entries

    reuse = reuse_attribution_summary()
    recent_enriched: list[dict[str, Any]] = []
    for c in recent:
        outcome = c.get("outcome")
        outcome_s = outcome.get("status") if isinstance(outcome, dict) else outcome
        entry: dict[str, Any] = {
            "ts": c.get("timestamp"),
            "outcome": outcome_s,
            "gene_id": c.get("gene_id") or c.get("selected_gene_id"),
            "run_id": c.get("run_id"),
            "type": c.get("type"),
        }
        rid = c.get("run_id")
        if rid and str(rid) in call_log_by_run:
            entries = call_log_by_run[str(rid)]
            tokens_spent = sum(
                int(e.get("tokens_spent", 0) or 0)
                for e in entries
                if isinstance(e.get("tokens_spent"), (int, float))
            )
            tokens_saved = sum(
                int(e.get("tokens_saved", 0) or 0)
                for e in entries
                if isinstance(e.get("tokens_saved"), (int, float))
            )
            asset_count = len({e.get("asset_id") for e in entries if e.get("asset_id")})
            entry["tokens_spent"] = tokens_spent
            entry["tokens_saved"] = tokens_saved
            entry["asset_calls"] = len(entries)
            entry["unique_assets"] = asset_count
        recent_enriched.append(entry)

    return {
        "total_cycles": total,
        "successes": successes,
        "failures": failures,
        "success_rate": round(rate, 3),
        "recent": recent_enriched,
        "reuse": {
            "total_reuse": reuse.get("total_reuse", 0),
            "total_reference": reuse.get("total_reference", 0),
            "total_tokens_saved": reuse.get("total_tokens_saved", 0),
            "top_assets": (reuse.get("by_asset") or [])[:5],
        },
    }


def list_runs(*, limit: int = 50, memory_dir: Path | None = None) -> dict[str, Any]:
    """Aggregate runs from events + asset call log (Node listRuns subset)."""
    from evolver.gep.paths import get_memory_dir

    mem = memory_dir or get_memory_dir()
    events = list(stream_jsonl(mem / "events.jsonl"))
    # Call log is evolution-scoped; still useful when path resolves under test env
    calls = read_call_log({"last": 2000})

    runs: dict[str, dict[str, Any]] = {}

    def merge(summary: dict[str, Any] | None) -> None:
        if not summary or not summary.get("runId"):
            return
        rid = str(summary["runId"])
        existing = runs.get(rid)
        if existing is None:
            runs[rid] = summary
            return
        # Prefer later timestamps
        if _ts(summary.get("updatedAt")) >= _ts(existing.get("updatedAt")):
            merged = {**existing, **{k: v for k, v in summary.items() if v is not None}}
            runs[rid] = merged

    for e in events:
        rid = e.get("run_id")
        if not rid:
            continue
        etype = e.get("type")
        if etype not in ("cycle_end", "EvolutionEvent", "solidify", "run"):
            continue
        outcome = e.get("outcome")
        status = "running"
        if outcome == "success" or (
            isinstance(outcome, dict) and outcome.get("status") == "success"
        ):
            status = "success"
        elif outcome in ("failure", "failed") or (
            isinstance(outcome, dict) and outcome.get("status") in ("failure", "failed")
        ):
            status = "failed"
        elif etype == "cycle_end":
            status = "success" if e.get("outcome") == "success" else "failed"
        merge(
            {
                "runId": str(rid),
                "status": status,
                "geneId": e.get("gene_id"),
                "updatedAt": e.get("timestamp"),
                "finishedAt": e.get("timestamp") if status != "running" else None,
                "source": "event",
            }
        )

    for c in calls:
        rid = c.get("run_id")
        if not rid:
            continue
        merge(
            {
                "runId": str(rid),
                "status": "running",
                "updatedAt": c.get("timestamp"),
                "source": "asset_call",
                "lastAction": c.get("action"),
            }
        )

    now_ms = time.time() * 1000.0
    items: list[dict[str, Any]] = []
    for run_row in runs.values():
        status = run_row.get("status") or "running"
        if status == "running" and not run_row.get("finishedAt"):
            t = _ts(run_row.get("updatedAt"))
            # ISO timestamps → seconds; numeric ms if large
            t_ms = t if t > 1e12 else t * 1000.0
            if t_ms and now_ms - t_ms > _STUCK_THRESHOLD_MS:
                status = "abandoned"
        items.append({**run_row, "status": status})

    items.sort(key=lambda r: _ts(r.get("updatedAt")), reverse=True)
    total = len(items)
    page_items = items[: max(1, limit)]
    return {"total": total, "items": page_items, "limit": limit}


def get_run(run_id: str, *, memory_dir: Path | None = None) -> dict[str, Any] | None:
    """Detail view for one run: events + asset calls."""
    from evolver.gep.asset_store import read_json_if_exists
    from evolver.gep.paths import get_memory_dir, get_solidify_state_path

    listing = list_runs(limit=500, memory_dir=memory_dir)
    run = next((r for r in listing["items"] if str(r.get("runId")) == str(run_id)), None)
    if run is None:
        # Still return partial if we only have call log / events
        run = {"runId": str(run_id), "status": "unknown"}

    mem = memory_dir or get_memory_dir()
    events = [e for e in stream_jsonl(mem / "events.jsonl") if _belongs_to_run(e, str(run_id))]
    # Redact message-like fields
    safe_events: list[dict[str, Any]] = []
    for e in events:
        row = dict(e)
        for k in ("summary", "message", "prompt"):
            if isinstance(row.get(k), str):
                row[k] = redact_text(row[k])
        safe_events.append(row)

    assets = read_call_log({"run_id": run_id})
    detail = None
    try:
        solidify = read_json_if_exists(get_solidify_state_path()) or {}
        last = solidify.get("last_run") if isinstance(solidify, dict) else None
        if isinstance(last, dict) and str(last.get("run_id")) == str(run_id):
            detail = {
                "parentEventId": last.get("parent_event_id"),
                "selectedCapsuleId": last.get("selected_capsule_id"),
                "signals": last.get("signals") or [],
                "selector": last.get("selector"),
                "mutation": last.get("mutation"),
                "sourceType": last.get("source_type"),
                "reusedAssetId": last.get("reused_asset_id"),
            }
    except Exception:
        detail = None

    return {
        **run,
        "detail": detail,
        "evidence": safe_events,
        "assets": assets,
        "event_count": len(safe_events),
        "asset_call_count": len(assets),
    }
