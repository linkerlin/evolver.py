"""ATP heartbeat signals handler.

Equivalent to ``evolver/src/atp/heartbeatSignalsHandler.js``.
Handles ATP-related directives received via heartbeat responses.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from evolver.atp.hub_client import submit_delivery

logger = logging.getLogger(__name__)

_LAST_RUN_AT: float = 0.0
_COOLDOWN_S = 30.0
_INFLIGHT = False


def collect_heartbeat_signals(body: dict[str, Any]) -> list[str]:
    """Extract text signals from a Hub heartbeat response body."""
    signals: list[str] = []

    for key in ("signals", "learning_signals", "capability_gaps"):
        raw = body.get(key, [])
        if not isinstance(raw, list):
            continue
        for item in raw:
            if isinstance(item, str) and item.strip():
                signals.append(item.strip())
            elif isinstance(item, dict):
                for field in ("message", "signal", "type", "text"):
                    value = item.get(field)
                    if isinstance(value, str) and value.strip():
                        signals.append(value.strip())
                        break

    pending = body.get("pending_atp_tasks", [])
    if isinstance(pending, list):
        for task in pending:
            if not isinstance(task, dict):
                continue
            for field in ("question", "title", "description"):
                value = task.get(field)
                if isinstance(value, str) and value.strip():
                    signals.append(value.strip())
                    break

    try:
        from evolver.gep.asset_store import pending_signals_path, read_json_if_exists

        pending_data = read_json_if_exists(pending_signals_path()) or {}
        for item in pending_data.get("signals", []):
            if isinstance(item, str) and item.strip():
                signals.append(item.strip())
    except Exception:
        pass

    return signals


async def handle_signals(body: dict[str, Any]) -> dict[str, Any]:
    """Process ATP signals from a heartbeat response."""
    global _LAST_RUN_AT, _INFLIGHT
    now = time.time()
    if now - _LAST_RUN_AT < _COOLDOWN_S:
        return {"ok": True, "skipped": "cooldown"}
    if _INFLIGHT:
        return {"ok": True, "skipped": "inflight"}

    _INFLIGHT = True
    summary: dict[str, Any] = {
        "ok": True,
        "deliveries": 0,
        "delivery_errors": 0,
        "pending_tasks": 0,
    }
    try:
        pending = body.get("pending_atp_tasks", [])
        deliveries = body.get("pending_deliveries", [])
        if isinstance(pending, list):
            summary["pending_tasks"] = len(pending)

        if isinstance(deliveries, list):
            for item in deliveries:
                if not isinstance(item, dict):
                    continue
                order_id = item.get("order_id")
                asset_id = item.get("result_asset_id")
                if order_id and asset_id:
                    proof = json.dumps({"heartbeat_delivery": True, "asset_id": asset_id})
                    result = await submit_delivery(order_id, proof, asset_id)
                    if result.get("ok"):
                        summary["deliveries"] += 1
                    else:
                        summary["delivery_errors"] += 1
                    logger.info("[ATP Signals] delivery %s: %s", order_id, result.get("ok"))

        signal_texts = collect_heartbeat_signals(body)
        summary["signals_collected"] = len(signal_texts)

        from evolver.atp import auto_buyer

        consent = auto_buyer.get_consent()
        if consent and consent.get("enabled"):
            buy_result = await auto_buyer.run_tick(signal_texts)
            summary["auto_buyer"] = buy_result

        from evolver.atp import auto_deliver

        deliver = getattr(handle_signals, "_auto_deliver", None)
        if deliver is not None and deliver.is_started():
            await deliver._tick()
            summary["auto_deliver_tick"] = True

        if pending and not deliveries:
            logger.warning(
                "[ATP Signals] %d pending tasks need manual execution (evolver run)",
                len(pending) if isinstance(pending, list) else 0,
            )
    finally:
        _INFLIGHT = False
        _LAST_RUN_AT = time.time()

    return summary


def bind_auto_deliver(agent: Any) -> None:
    """Register a running :class:`AutoDeliver` for heartbeat ticks."""
    handle_signals._auto_deliver = agent  # type: ignore[attr-defined]


__all__ = ["bind_auto_deliver", "collect_heartbeat_signals", "handle_signals"]
