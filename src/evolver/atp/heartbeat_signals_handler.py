"""ATP heartbeat signals handler.

Equivalent to ``evolver/src/atp/heartbeatSignalsHandler.js``.
Handles ATP-related directives received via heartbeat responses.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from evolver.atp.hub_client import submit_delivery

logger = logging.getLogger(__name__)

_LAST_RUN_AT: float = 0.0
_COOLDOWN_S = 30.0
_INFLIGHT = False


async def handle_signals(body: dict[str, Any]) -> None:
    """Process ATP signals from a heartbeat response."""
    global _LAST_RUN_AT, _INFLIGHT
    now = time.time()
    if now - _LAST_RUN_AT < _COOLDOWN_S:
        return
    if _INFLIGHT:
        return
    _INFLIGHT = True
    try:
        pending = body.get("pending_atp_tasks", [])
        deliveries = body.get("pending_deliveries", [])
        for item in deliveries:
            order_id = item.get("order_id")
            asset_id = item.get("result_asset_id")
            if order_id and asset_id:
                proof = json.dumps({"heartbeat_delivery": True, "asset_id": asset_id})
                result = await submit_delivery(order_id, proof, asset_id)
                logger.info("[ATP Signals] delivery %s: %s", order_id, result.get("ok"))
        if pending and not deliveries:
            logger.warning("[ATP Signals] %d pending tasks need manual execution (evolver run)", len(pending))
    finally:
        _INFLIGHT = False
        _LAST_RUN_AT = time.time()
