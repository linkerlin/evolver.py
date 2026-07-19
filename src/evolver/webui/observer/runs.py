"""Evolution run history statistics for WebUI — with asset call log correlation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from evolver.gep.asset_call_log import read_call_log, reuse_attribution_summary

from .jsonl import stream_jsonl


def runs_history(*, limit: int = 50, memory_dir: Path | None = None) -> dict[str, Any]:
    """Return run-level statistics enriched with asset reuse and token costs."""
    from evolver.gep.paths import get_memory_dir

    mem = memory_dir or get_memory_dir()
    events = list(stream_jsonl(mem / "events.jsonl"))

    cycles = [e for e in events if e.get("type") == "cycle_end"]
    total = len(cycles)
    successes = sum(1 for c in cycles if c.get("outcome") == "success")
    failures = total - successes
    rate = successes / total if total else 0.0

    # Collect run_ids from recent cycles for call-log correlation
    recent = cycles[-limit:]
    recent.reverse()
    run_ids = [c.get("run_id") for c in recent if c.get("run_id")]

    # Per-run call log enrichment
    call_log_by_run: dict[str, list[dict[str, Any]]] = {}
    for rid in run_ids:
        entries = read_call_log({"run_id": rid})
        if entries:
            call_log_by_run[str(rid)] = entries

    # Global reuse summary
    reuse = reuse_attribution_summary()

    recent_enriched = []
    for c in recent:
        entry: dict[str, Any] = {
            "ts": c.get("timestamp"),
            "outcome": c.get("outcome"),
            "gene_id": c.get("gene_id"),
        }
        rid = c.get("run_id")
        if rid and rid in call_log_by_run:
            entries = call_log_by_run[str(rid)]
            tokens_spent = sum(
                int(e.get("tokens_spent", 0))
                for e in entries
                if isinstance(e.get("tokens_spent"), (int, float))
            )
            tokens_saved = sum(
                int(e.get("tokens_saved", 0))
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
