"""Background loop that periodically runs ``SkillUpdater.process_updates()``."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from evolver.proxy.router.features import is_route_enabled

if TYPE_CHECKING:
    from evolver.proxy.extensions.skill_updater import SkillUpdater

logger = logging.getLogger(__name__)

DEFAULT_SKILL_UPDATE_INTERVAL_SEC = 300.0


def _interval_sec() -> float:
    raw = os.environ.get("EVOLVER_SKILL_UPDATE_INTERVAL_SEC", "").strip()
    if not raw:
        return DEFAULT_SKILL_UPDATE_INTERVAL_SEC
    try:
        return max(30.0, float(raw))
    except ValueError:
        return DEFAULT_SKILL_UPDATE_INTERVAL_SEC


class SkillUpdateLoop:
    """Poll Hub on an interval and auto-apply skill updates when enabled."""

    def __init__(self, updater: SkillUpdater) -> None:
        self._updater = updater
        self._task: asyncio.Task[None] | None = None
        self._shutdown = asyncio.Event()

    def start(self, interval_sec: float | None = None) -> None:
        if self._task is not None and not self._task.done():
            return
        self._shutdown.clear()
        delay = interval_sec if interval_sec is not None else _interval_sec()
        self._task = asyncio.create_task(self._run(delay))
        logger.info("[SkillUpdateLoop] Started (interval=%.0fs)", delay)

    def stop(self) -> None:
        self._shutdown.set()
        if self._task is not None:
            self._task.cancel()
        logger.info("[SkillUpdateLoop] Stopped.")

    async def _run(self, interval_sec: float) -> None:
        while not self._shutdown.is_set():
            if is_route_enabled("skill_update") and not self._updater.disabled:
                try:
                    result = await self._updater.process_updates()
                    applied = result.get("applied", [])
                    if applied:
                        logger.info("[SkillUpdateLoop] Applied %d skill update(s)", len(applied))
                except Exception as exc:
                    logger.warning("[SkillUpdateLoop] Tick error: %s", exc)
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=interval_sec)
            except TimeoutError:
                pass


__all__ = ["DEFAULT_SKILL_UPDATE_INTERVAL_SEC", "SkillUpdateLoop"]
