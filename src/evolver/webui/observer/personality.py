"""Personality state visualization data for WebUI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def personality_data(memory_dir: Path | None = None) -> dict[str, Any]:
    """Return personality radar-chart data and recent adaptations."""
    from evolver.gep.paths import get_memory_dir

    mem = memory_dir or get_memory_dir()
    path = mem / "personality.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {}

    # Normalize to radar dimensions
    dimensions = {
        "risk_tolerance": data.get("risk_tolerance", 0.5),
        "exploration_rate": data.get("exploration_rate", 0.3),
        "verbosity": data.get("verbosity", 0.5),
        "caution": data.get("caution", 0.5),
        "persistence": data.get("persistence", 0.5),
    }

    return {
        "dimensions": dimensions,
        "adaptations": data.get("adaptations", []),
        "updated_at": data.get("updated_at"),
    }
