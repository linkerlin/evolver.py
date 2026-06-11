"""Pipeline event timeline for WebUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .jsonl import stream_jsonl


def pipeline_timeline(*, limit: int = 100, memory_dir: Path | None = None) -> list[dict[str, Any]]:
    """Return recent pipeline-phase events for timeline visualization."""
    from evolver.gep.paths import get_memory_dir

    mem = memory_dir or get_memory_dir()
    events = list(stream_jsonl(mem / "events.jsonl", limit=limit * 3))
    pipeline = [
        e
        for e in events
        if e.get("type")
        in ("pipeline_start", "pipeline_phase", "pipeline_end", "cycle_start", "cycle_end")
    ]
    pipeline = pipeline[-limit:]
    return pipeline
