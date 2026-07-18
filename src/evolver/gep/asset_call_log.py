"""Append-only asset call log for tracking Hub asset interactions per run.

Equivalent to ``evolver/src/gep/assetCallLog.js``.
Log file: ``<EVOLUTION_DIR>/asset_call_log.jsonl``.

Actions: ``hub_search_hit`` | ``hub_search_miss`` | ``asset_reuse`` |
``asset_reference`` | ``asset_publish`` | ``asset_publish_skip`` |
``asset_inject`` | ``asset_inject_shadow``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evolver.gep.paths import get_evolution_dir

LOG_FILE_NAME = "asset_call_log.jsonl"


def get_log_path() -> Path:
    return get_evolution_dir() / LOG_FILE_NAME


def log_asset_call(entry: dict[str, Any] | None) -> None:
    """Append a single asset call record. Never raises (logging is non-fatal)."""
    if not isinstance(entry, dict):
        return
    try:
        log_path = get_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            **entry,
        }
        with log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError):
        pass  # never block evolution for logging failure


def _parse_timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def read_call_log(opts: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Read log entries with optional ``run_id``/``action``/``last``/``since`` filters."""
    options = opts or {}
    log_path = get_log_path()
    if not log_path.exists():
        return []

    entries: list[dict[str, Any]] = []
    try:
        raw = log_path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue  # skip corrupt lines
        if isinstance(parsed, dict):
            entries.append(parsed)

    since_ts = _parse_timestamp(options.get("since"))
    if since_ts is not None:
        entries = [
            entry
            for entry in entries
            if (ts := _parse_timestamp(entry.get("timestamp"))) is not None and ts >= since_ts
        ]

    if options.get("run_id"):
        entries = [entry for entry in entries if entry.get("run_id") == options["run_id"]]

    if options.get("action"):
        entries = [entry for entry in entries if entry.get("action") == options["action"]]

    last = options.get("last")
    if isinstance(last, int) and last > 0:
        entries = entries[-last:]

    return entries


def summarize_call_log(opts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Summarize the call log for CLI display (same filters as read_call_log)."""
    entries = read_call_log(opts)
    action_counts: dict[str, int] = {}
    assets_seen: set[str] = set()
    runs_seen: set[str] = set()

    for entry in entries:
        action = str(entry.get("action") or "unknown")
        action_counts[action] = action_counts.get(action, 0) + 1
        if entry.get("asset_id"):
            assets_seen.add(str(entry["asset_id"]))
        if entry.get("run_id"):
            runs_seen.add(str(entry["run_id"]))

    return {
        "total_entries": len(entries),
        "unique_assets": len(assets_seen),
        "unique_runs": len(runs_seen),
        "by_action": action_counts,
        "entries": entries,
    }


def reuse_attribution_summary(opts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Local-only reuse-attribution rollup (P4-a Slice A).

    Aggregates this node's ``asset_reuse``/``asset_reference`` entries per
    reused asset without any network call.
    """
    entries = [
        entry
        for entry in read_call_log(opts)
        if entry.get("action") in ("asset_reuse", "asset_reference")
    ]
    by_asset: dict[str, dict[str, Any]] = {}
    total_tokens_saved = 0
    for entry in entries:
        asset_id = str(entry.get("asset_id") or "(unknown)")
        agg = by_asset.get(asset_id)
        if agg is None:
            agg = {
                "asset_id": asset_id,
                "source_node_id": entry.get("source_node_id") or None,
                "chain_id": entry.get("chain_id") or None,
                "reuse": 0,
                "reference": 0,
                "tokens_saved": 0,
            }
            by_asset[asset_id] = agg
        if entry.get("action") == "asset_reuse":
            agg["reuse"] += 1
        else:
            agg["reference"] += 1
        tokens_saved = entry.get("tokens_saved")
        if isinstance(tokens_saved, (int, float)) and tokens_saved > 0:
            agg["tokens_saved"] += int(tokens_saved)
            total_tokens_saved += int(tokens_saved)
        # keep first-seen source/chain; do not trust later rows to overwrite
        if not agg["source_node_id"] and entry.get("source_node_id"):
            agg["source_node_id"] = entry["source_node_id"]
        if not agg["chain_id"] and entry.get("chain_id"):
            agg["chain_id"] = entry["chain_id"]

    by_asset_sorted = sorted(
        by_asset.values(),
        key=lambda row: row["reuse"] + row["reference"],
        reverse=True,
    )
    return {
        "total_reuse": sum(1 for entry in entries if entry.get("action") == "asset_reuse"),
        "total_reference": sum(1 for entry in entries if entry.get("action") == "asset_reference"),
        "total_tokens_saved": total_tokens_saved,
        "by_asset": by_asset_sorted,
    }


def asset_cost_index(opts: dict[str, Any] | None = None) -> dict[str, int]:
    """Map asset_id -> real tokens spent deriving it (later publish rows win)."""
    index: dict[str, int] = {}
    for entry in read_call_log(opts):
        if entry.get("action") != "asset_publish" or not entry.get("asset_id"):
            continue
        spent = entry.get("tokens_spent")
        if isinstance(spent, (int, float)) and spent > 0:
            index[str(entry["asset_id"])] = int(spent)
    return index


__all__ = [
    "asset_cost_index",
    "get_log_path",
    "log_asset_call",
    "read_call_log",
    "reuse_attribution_summary",
    "summarize_call_log",
]
