"""Evolution narrative observer — markdown timeline + reflection log."""

from __future__ import annotations

import json
from typing import Any

from evolver.gep.paths import get_narrative_path, get_reflection_log_path


def narrative_history(*, limit: int = 20) -> str:
    """Return the tail of the evolution narrative markdown."""
    path = get_narrative_path()
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) <= limit * 6:
        return text
    return "\n".join(lines[-(limit * 6) :])


def reflection_entries(*, limit: int = 50) -> list[dict[str, Any]]:
    """Return recent reflection log entries."""
    path = get_reflection_log_path()
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return entries[-limit:]


def narrative_summary() -> dict[str, Any]:
    """Summary for dashboard panel."""
    path = get_narrative_path()
    has_narrative = path.exists()
    size = path.stat().st_size if has_narrative else 0
    refl = reflection_entries(limit=1)
    last_reflection = refl[0] if refl else None
    return {
        "has_narrative": has_narrative,
        "size_bytes": size,
        "reflection_count": len(reflection_entries(limit=10_000)),
        "last_reflection": last_reflection,
    }
