"""Post-cycle hooks after dispatch (ATP, task pickup).

Runs lightweight side effects that should not block the core GEP prompt path.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _signal_texts(ctx: dict[str, Any]) -> list[str]:
    raw = ctx.get("signals", [])
    if not isinstance(raw, list):
        return []
    return [str(s) for s in raw if s]


async def run_post_cycle_hooks(ctx: dict[str, Any]) -> dict[str, Any]:
    """Run ATP auto-buyer and optional task pickup after a cycle."""
    signals = _signal_texts(ctx)
    if not signals:
        return ctx

    from evolver.gep.feature_flags import is_enabled
    from evolver.solo.breaker import is_solo_active

    # Solo "禁ATP": cut auto-spend and task pickup at the in-cycle path even if
    # the user forced ATP on (the startup path already overrode the env).
    if not is_solo_active() and is_enabled("enable_auto_buyer"):
        try:
            from evolver.atp import auto_buyer

            consent = auto_buyer.get_consent()
            if consent and consent.get("enabled"):
                result = await auto_buyer.run_tick(signals)
                ctx["atp_auto_buyer"] = result
                if result.get("placed", 0) > 0:
                    logger.info("[post_cycle] ATP auto-buyer placed %s order(s)", result["placed"])
        except Exception as exc:
            logger.warning("[post_cycle] ATP auto-buyer failed: %s", exc)
            ctx["atp_auto_buyer_error"] = str(exc)

    if not is_solo_active():
        try:
            from evolver.atp.atp_task_pickup import pick_one

            spawn = await pick_one()
            if spawn:
                ctx["atp_spawn_instruction"] = spawn
                logger.info("[post_cycle] ATP task pickup produced spawn instruction")
        except Exception as exc:
            logger.debug("[post_cycle] ATP task pickup skipped: %s", exc)

    try:
        from evolver.gep.issue_reporter import report_recurring_failures
        from evolver.gep.memory_graph import read_all

        events = ctx.get("recent_events")
        if not isinstance(events, list) or not events:
            events = read_all(limit=500)
        created = report_recurring_failures(events=events)
        if created:
            ctx["issue_reporter_urls"] = created
            logger.info("[post_cycle] issue reporter created %s issue(s)", len(created))
    except Exception as exc:
        logger.debug("[post_cycle] issue reporter skipped: %s", exc)

    return ctx


__all__ = ["run_post_cycle_hooks"]
