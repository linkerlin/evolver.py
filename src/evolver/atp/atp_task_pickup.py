"""ATP task pickup — pick available tasks from Hub and build spawn instructions.

Equivalent to ``evolver/src/atp/atpTaskPickup.js``.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from evolver.atp.hub_client import list_my_tasks
from evolver.gep.paths import get_memory_dir

logger = logging.getLogger(__name__)

_LEDGER_FILENAME = "atp-pickup-ledger.json"
_COOLDOWN_S = 300


def _ledger_path() -> Path:
    return get_memory_dir() / _LEDGER_FILENAME


def _read_ledger() -> dict[str, Any]:
    p = _ledger_path()
    if not p.exists():
        return {"version": 1, "spawned": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
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


async def pick_one() -> str | None:
    """Try to pick one task and return a spawn instruction string, or None."""
    ledger = _read_ledger()
    spawned = ledger.get("spawned", {})

    result = await list_my_tasks()
    if not result.get("ok"):
        return None

    for task in result.get("data", {}).get("tasks", []):
        task_id = task.get("task_id")
        if not task_id:
            continue
        if task_id in spawned:
            continue
        order_id = task.get("atp_order_id")
        if not order_id:
            continue
        if task.get("result_asset_id"):
            continue
        status = task.get("status", "")
        if status not in ("claimed", "open"):
            continue

        question = (task.get("question", "") or task.get("payload", {}).get("question", ""))[:12000]
        answer_path = get_memory_dir() / "atp_answers" / f"{_safe_filename(task_id)}.md"
        answer_path.parent.mkdir(parents=True, exist_ok=True)

        spawn = (
            f"# ATP Task {task_id}\n"
            f"Order: {order_id}\n"
            f"Question: {question}\n"
            f"Write answer to: {answer_path}\n"
            f"Then run: python -m evolver.atp.atp_execute --task-id={task_id} --answer-file={answer_path}\n"
        )
        spawned[task_id] = {"at": time.time(), "order_id": order_id}
        _write_ledger(ledger)
        return spawn

    return None


def forget(task_id: str) -> None:
    """Remove task from ledger so it can be retried."""
    ledger = _read_ledger()
    ledger.get("spawned", {}).pop(task_id, None)
    _write_ledger(ledger)
