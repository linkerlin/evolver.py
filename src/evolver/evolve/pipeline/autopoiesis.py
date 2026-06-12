"""Autopoiesis phase — viability assessment and homeostasis regulation."""

from __future__ import annotations

from typing import Any

from evolver.gep.autopoiesis import run_autopoiesis_tick


async def autopoiesis_phase(ctx: dict[str, Any]) -> dict[str, Any]:
    """Run autopoiesis after enrich so hub/signals/diagnosis are available."""
    return run_autopoiesis_tick(ctx)
