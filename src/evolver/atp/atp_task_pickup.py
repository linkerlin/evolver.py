"""ATP task pickup — select high-ROI tasks matching local capabilities.

Equivalent to ``evolver/src/atp/atpTaskPickup.js`` (209 lines).

Scans available Hub tasks, scores them by ROI (bounty / estimated effort)
and capability match (task signals vs local gene pool), and returns spawn
instructions for the best candidate. Maintains a ledger to prevent
re-spawning the same task and enforces a concurrency limit.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, cast

from evolver.atp.hub_client import list_my_tasks, list_open_tasks
from evolver.gep.paths import get_memory_dir

logger = logging.getLogger(__name__)

_LEDGER_FILENAME = "atp-pickup-ledger.json"
_COOLDOWN_S = 300
_MAX_CONCURRENT = 3
_MIN_ROI = 1.0
_MIN_CAPABILITY_MATCH = 0.3


def _ledger_path() -> Path:
    return get_memory_dir() / _LEDGER_FILENAME


def _read_ledger() -> dict[str, Any]:
    p = _ledger_path()
    if not p.exists():
        return {"version": 1, "spawned": {}}
    try:
        return cast(dict[str, Any], json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "spawned": {}}


def _write_ledger(ledger: dict[str, Any]) -> None:
    p = _ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    spawned = ledger.get("spawned", {})
    if len(spawned) > 500:
        sorted_items = sorted(spawned.items(), key=lambda x: x[1].get("at", 0))
        ledger["spawned"] = dict(sorted_items[-500:])
    p.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")


def _safe_filename(task_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", task_id)


# ---------------------------------------------------------------------------
# ROI scoring + capability matching
# ---------------------------------------------------------------------------


def _estimate_effort(task: dict[str, Any]) -> float:
    """Estimate relative effort for a task (1.0 = trivial, 10.0 = hard)."""
    question = task.get("question", "") or task.get("payload", {}).get("question", "")
    # Simple heuristic: longer questions = more complex.
    length_factor = min(len(question) / 2000.0, 5.0)
    # Multiple capabilities = more work.
    caps = task.get("capabilities", [])
    cap_factor = max(1.0, len(caps) * 0.5)
    return length_factor + cap_factor


def _compute_roi(task: dict[str, Any]) -> float:
    """Compute ROI = bounty / estimated_effort."""
    bounty = float(task.get("bounty", task.get("reward", 1.0)))
    effort = _estimate_effort(task)
    if effort <= 0:
        return 0.0
    return bounty / effort


def _compute_capability_match(
    task: dict[str, Any], gene_pool: list[dict[str, Any]] | None = None
) -> float:
    """Score how well the task matches local gene capabilities (0.0-1.0)."""
    task_caps = set(task.get("capabilities", []))
    task_signals = set(task.get("signals", []))
    if not task_caps and not task_signals:
        return 1.0  # no requirements → universal match

    if not gene_pool:
        # Without a gene pool, check if any task capability is a known signal.
        known_signals = {"repair", "optimize", "innovate", "log_error", "test_failure"}
        overlap = task_signals & known_signals
        return min(1.0, len(overlap) / max(len(task_signals), 1)) if task_signals else 0.5

    pool_signals: set[str] = set()
    for gene in gene_pool:
        for sig in gene.get("signals_match", []):
            pool_signals.add(sig.split("|")[0].strip())

    overlap = (task_caps | task_signals) & pool_signals
    total = task_caps | task_signals
    return len(overlap) / max(len(total), 1) if total else 1.0


def _score_task(
    task: dict[str, Any], gene_pool: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Score a task and return {roi, capability_match, eligible}."""
    roi = _compute_roi(task)
    cap_match = _compute_capability_match(task, gene_pool)
    eligible = roi >= _MIN_ROI and cap_match >= _MIN_CAPABILITY_MATCH
    return {"roi": round(roi, 2), "capability_match": round(cap_match, 2), "eligible": eligible}


def _active_task_count(ledger: dict[str, Any]) -> int:
    """Count tasks spawned but not yet completed (within cooldown)."""
    now = time.time()
    spawned = ledger.get("spawned", {})
    return sum(
        1
        for entry in spawned.values()
        if isinstance(entry, dict) and now - entry.get("at", 0) < _COOLDOWN_S
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def pick_one(
    *,
    gene_pool: list[dict[str, Any]] | None = None,
    use_open_tasks: bool = False,
) -> str | None:
    """Try to pick one task and return a spawn instruction string, or None.

    Scoring: ROI * capability_match. Skips ineligible tasks, already-spawned
    tasks, completed tasks, and respects the concurrent limit.
    """
    ledger = _read_ledger()
    spawned = ledger.get("spawned", {})

    if _active_task_count(ledger) >= _MAX_CONCURRENT:
        logger.debug("[ATP-pickup] Concurrent limit (%d) reached", _MAX_CONCURRENT)
        return None

    fetcher = list_open_tasks if use_open_tasks else list_my_tasks
    result = await fetcher()
    if not result.get("ok"):
        return None

    tasks = result.get("data", {}).get("tasks", [])
    candidates: list[tuple[float, dict[str, Any], dict[str, Any]]] = []

    for task in tasks:
        task_id = task.get("task_id")
        if not task_id or task_id in spawned:
            continue
        if task.get("result_asset_id"):
            continue
        status = task.get("status", "")
        if status not in ("claimed", "open"):
            continue

        score = _score_task(task, gene_pool)
        if not score["eligible"]:
            continue
        combined = score["roi"] * score["capability_match"]
        candidates.append((combined, task, score))

    if not candidates:
        return None

    # Pick the highest-scoring candidate.
    candidates.sort(key=lambda c: c[0], reverse=True)
    _, task, score = candidates[0]

    task_id = task["task_id"]
    order_id = task.get("atp_order_id", "")
    question = (task.get("question", "") or task.get("payload", {}).get("question", ""))[:12000]
    answer_path = get_memory_dir() / "atp_answers" / f"{_safe_filename(task_id)}.md"
    answer_path.parent.mkdir(parents=True, exist_ok=True)

    spawn = (
        f"# ATP Task {task_id}\n"
        f"Order: {order_id}\n"
        f"ROI: {score['roi']} | Capability match: {score['capability_match']}\n"
        f"Question: {question}\n"
        f"Write answer to: {answer_path}\n"
        "Then run: python -m evolver.atp.atp_execute "
        f"--task-id={task_id} --answer-file={answer_path}\n"
    )
    spawned[task_id] = {
        "at": time.time(),
        "order_id": order_id,
        "roi": score["roi"],
        "capability_match": score["capability_match"],
    }
    _write_ledger(ledger)
    return spawn


def forget(task_id: str) -> None:
    """Remove task from ledger so it can be retried."""
    ledger = _read_ledger()
    ledger.get("spawned", {}).pop(task_id, None)
    _write_ledger(ledger)


__all__ = ["forget", "pick_one"]
