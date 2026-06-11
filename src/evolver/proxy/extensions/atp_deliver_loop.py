"""Background wrapper to start/stop :class:`AutoDeliver` with the proxy."""

from __future__ import annotations

import logging
import os

from evolver.atp.auto_deliver import AutoDeliver
from evolver.atp.heartbeat_signals_handler import bind_auto_deliver

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return os.environ.get("EVOLVER_ATP_AUTODELIVER", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


class AtpDeliverLoop:
    def __init__(self, poll_interval_s: float = 60.0) -> None:
        self._agent = AutoDeliver(poll_interval_s=poll_interval_s)
        self._started = False

    def start(self) -> None:
        if self._started or not _enabled():
            return
        self._agent.start()
        bind_auto_deliver(self._agent)
        self._started = True
        logger.info("[AtpDeliverLoop] Started")

    def stop(self) -> None:
        if not self._started:
            return
        self._agent.stop()
        bind_auto_deliver(None)
        self._started = False
        logger.info("[AtpDeliverLoop] Stopped")


__all__ = ["AtpDeliverLoop"]
