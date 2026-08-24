"""Idempotency — persisted ``once(cycle_id, op_key)`` dedup.

Concept harvest from Node v2 ``daemon/idempotency.js`` (behavioral
re-implementation; no code copied). Prevents double-fire of non-idempotent
post-cycle operations (ATP auto-buyer ticks, task pickups) when a cycle is
retried after timeout/crash.

Storage: append-only JSONL at ``<EVOLUTION_DIR>/idempotency.jsonl`` — the
last record for a key wins, matching the repo's overlay-by-append idiom.
Records older than :data:`IDEMPOTENCY_TTL_DAYS` are ignored (and pruned on
compaction), so long-lived workspaces don't accumulate unbounded state.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

IDEMPOTENCY_FILENAME = "idempotency.jsonl"
IDEMPOTENCY_TTL_DAYS: int = 7


def idempotency_path() -> Path:
    from evolver.gep.paths import get_evolution_dir

    return get_evolution_dir() / IDEMPOTENCY_FILENAME


def _key(cycle_id: str, op_key: str) -> str:
    return f"{cycle_id}:{op_key}"


def _read_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    records.append(parsed)
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return records


def already_done(cycle_id: str, op_key: str, *, now: float | None = None) -> bool:
    """Return True when this (cycle_id, op_key) pair was already executed."""
    current = now if now is not None else time.time()
    ttl_s = IDEMPOTENCY_TTL_DAYS * 86400.0
    target = _key(cycle_id, op_key)
    for record in _read_records(idempotency_path()):
        if str(record.get("key")) != target or not bool(record.get("done")):
            continue
        ts = record.get("ts")
        if isinstance(ts, (int, float)) and current - float(ts) > ttl_s:
            continue
        return True
    return False


def mark_done(cycle_id: str, op_key: str, *, now: float | None = None) -> None:
    """Persist completion for a (cycle_id, op_key) pair."""
    current = now if now is not None else time.time()
    record = {"key": _key(cycle_id, op_key), "done": True, "ts": current}
    path = idempotency_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.debug("[Idempotency] persist failed: %s", exc)


def once(cycle_id: str, op_key: str) -> bool:
    """True exactly once per (cycle_id, op_key); side-effect guard.

    Usage::

        if once(ctx["cycle_id"], "atp_auto_buyer_tick"):
            await run_tick(...)
    """
    if already_done(cycle_id, op_key):
        return False
    mark_done(cycle_id, op_key)
    return True


__all__ = [
    "IDEMPOTENCY_FILENAME",
    "IDEMPOTENCY_TTL_DAYS",
    "already_done",
    "idempotency_path",
    "mark_done",
    "once",
]
