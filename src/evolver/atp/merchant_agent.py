"""ATP merchant agent template.

Equivalent to ``evolver/src/atp/merchantAgent.js``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from evolver.atp.hub_client import (
    get_merchant_tier,
    list_my_tasks,
    list_proofs,
    submit_delivery,
)
from evolver.atp.service_helper import publish
from evolver.gep.a2a_protocol import send_hello

logger = logging.getLogger(__name__)

PollHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any] | None]]


class MerchantAgent:
    def __init__(
        self,
        services: list[dict[str, Any]],
        on_order: PollHandler,
        *,
        poll_interval_s: float = 30.0,
    ) -> None:
        self.services = services
        self.on_order = on_order
        self.poll_interval_s = poll_interval_s
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        await send_hello()
        for svc in self.services:
            result = await publish(**svc)
            logger.info("[Merchant] publish %s: %s", svc.get("title"), result)
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("[Merchant] Agent started.")

    def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
        logger.info("[Merchant] Agent stopped.")

    def is_running(self) -> bool:
        return self._running

    async def get_status(self) -> dict[str, Any]:
        tier = await get_merchant_tier()
        proofs = await list_proofs()
        return {
            "running": self._running,
            "tier": tier.get("data") if tier.get("ok") else None,
            "proofs": proofs.get("data", {}).get("proofs", []) if proofs.get("ok") else [],
        }

    async def _loop(self) -> None:
        while self._running:
            try:
                tasks = await list_my_tasks()
                if tasks.get("ok"):
                    for task in tasks.get("data", {}).get("tasks", []):
                        if not self._running:
                            break
                        result = await self.on_order(task)
                        if result and task.get("atp_order_id"):
                            await submit_delivery(
                                task["atp_order_id"],
                                result.get("proof", ""),
                                result.get("result_asset_id"),
                            )
            except Exception as exc:
                logger.warning("[Merchant] Poll error: %s", exc)
            try:
                await asyncio.wait_for(
                    asyncio.sleep(self.poll_interval_s),
                    timeout=self.poll_interval_s + 5,
                )
            except TimeoutError:
                pass
