"""ATP auto-deliver — merchant-side automatic delivery.

Equivalent to ``evolver/src/atp/autoDeliver.js``.
Default-enabled (opt-out). Polls ``/a2a/task/my`` and submits delivery
proofs for completed tasks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, cast

from evolver.atp.default_handler import default_order_handler
from evolver.atp.hub_client import list_my_tasks, submit_delivery
from evolver.gep.paths import get_memory_dir

logger = logging.getLogger(__name__)

_LEDGER_FILENAME = "atp-autodeliver-ledger.json"
_DEFAULT_POLL_INTERVAL_S = 60.0
_MIN_POLL_INTERVAL_S = 15.0


class AutoDeliver:
    def __init__(self, poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S) -> None:
        self.poll_interval_s = max(poll_interval_s, _MIN_POLL_INTERVAL_S)
        self._running = False
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("[AutoDeliver] Started (interval=%.0fs)", self.poll_interval_s)

    def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
        logger.info("[AutoDeliver] Stopped.")

    def is_started(self) -> bool:
        return self._running

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except Exception as exc:
                logger.warning("[AutoDeliver] Tick error: %s", exc)
            try:
                await asyncio.wait_for(
                    asyncio.sleep(self.poll_interval_s), timeout=self.poll_interval_s + 5
                )
            except TimeoutError:
                pass

    async def _tick(self) -> None:
        result = await list_my_tasks()
        if not result.get("ok"):
            return
        for task in result.get("data", {}).get("tasks", []):
            await self._handle_task(task)

    async def _handle_task(self, task: dict[str, Any]) -> None:
        order_id = task.get("atp_order_id")
        if not order_id:
            return
        status = task.get("status", "")
        if status not in ("claimed", "completed"):
            return
        if _already_submitted(order_id):
            return

        result_asset_id = task.get("result_asset_id")
        if not result_asset_id and status == "claimed":
            handled = default_order_handler(task)
            result_asset_id = handled.get("result_asset_id") or f"local:{order_id}"
            proof = json.dumps(
                {
                    "task_id": task.get("task_id"),
                    "processor": handled.get("processor", "evolver-default"),
                    "output": handled.get("output", ""),
                }
            )
            delivery = await submit_delivery(order_id, proof, result_asset_id)
            if delivery.get("ok"):
                _mark_submitted(order_id, success=True)
                logger.info("[AutoDeliver] Delivered claimed task %s via default handler", order_id)
            else:
                status_code = delivery.get("status")
                if status_code in (400, 404, 409):
                    _mark_submitted(order_id, success=False)
                logger.warning(
                    "[AutoDeliver] Default delivery failed for %s: %s",
                    order_id,
                    delivery.get("error"),
                )
            return

        if not result_asset_id:
            return

        proof = json.dumps({"task_id": task.get("task_id"), "asset_id": result_asset_id})
        delivery = await submit_delivery(order_id, proof, result_asset_id)
        if delivery.get("ok"):
            _mark_submitted(order_id, success=True)
            logger.info("[AutoDeliver] Delivered %s", order_id)
        else:
            status_code = delivery.get("status")
            if status_code in (400, 404, 409):
                _mark_submitted(order_id, success=False)
            logger.warning(
                "[AutoDeliver] Delivery failed for %s: %s", order_id, delivery.get("error")
            )


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def _ledger_path() -> Path:
    return get_memory_dir() / _LEDGER_FILENAME


def _read_ledger() -> dict[str, Any]:
    p = _ledger_path()
    if not p.exists():
        return {"version": 1, "submitted": {}}
    try:
        return cast(dict[str, Any], json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "submitted": {}}


def _write_ledger(ledger: dict[str, Any]) -> None:
    p = _ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # Trim to 500 entries
    submitted = ledger.get("submitted", {})
    if len(submitted) > 500:
        sorted_items = sorted(submitted.items(), key=lambda x: abs(x[1]))
        ledger["submitted"] = dict(sorted_items[-500:])
    p.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")


def _already_submitted(order_id: str) -> bool:
    return order_id in _read_ledger().get("submitted", {})


def _mark_submitted(order_id: str, success: bool) -> None:
    ledger = _read_ledger()
    ts = time.time() if success else -time.time()
    ledger.setdefault("submitted", {})[order_id] = ts
    _write_ledger(ledger)
