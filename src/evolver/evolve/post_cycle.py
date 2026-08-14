"""Post-cycle hooks after dispatch (ATP, task pickup).

Runs lightweight side effects that should not block the core GEP prompt path.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from evolver.gep.hooks.merge_integration import merge_accepted_candidates

logger = logging.getLogger(__name__)


def _persist_atp_spawn(spawn: str) -> None:
    """Sprint 22.1 (§13.3-#5): persist the spawn instruction so an external
    agent/bridge can consume it after the cycle ends (ctx dies with the cycle)."""
    try:
        from evolver.gep.paths import get_evolution_dir

        path = Path(get_evolution_dir()) / "atp_spawn_instruction.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "instruction": spawn,
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        logger.info("[post_cycle] ATP spawn instruction persisted: %s", path)
    except Exception as exc:
        logger.debug("[post_cycle] ATP spawn persist skipped: %s", exc)


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
                _persist_atp_spawn(spawn)
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

    # Self-Harness C3: merge multiple accepted candidates (contract-driven;
    # no-op unless ctx["accepted_candidates"] is present with >1 entries).
    _merge_accepted_candidates(ctx)
    return ctx


def _merge_accepted_candidates(ctx: dict[str, Any]) -> None:
    """Merge ``ctx["accepted_candidates"]`` (>1) into ``ctx["merged_candidates"]``."""
    accepted = ctx.get("accepted_candidates")
    if not isinstance(accepted, list) or len(accepted) <= 1:
        return
    try:
        merged = merge_accepted_candidates(accepted)
        ctx["merged_candidates"] = merged
        conflicts = [m for m in merged if m.get("conflict")]
        if conflicts:
            logger.warning(
                "[post_cycle] %s merge conflict(s) among accepted candidates",
                len(conflicts),
            )
    except Exception as exc:
        logger.debug("[post_cycle] candidate merge skipped: %s", exc)


__all__ = ["run_post_cycle_hooks"]
