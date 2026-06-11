"""Safety event aggregation for WebUI."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .jsonl import stream_jsonl


def safety_events(*, limit: int = 100, memory_dir: Path | None = None) -> dict[str, Any]:
    """Return recent safety/policy events and severity counts."""
    from evolver.gep.paths import get_memory_dir

    mem = memory_dir or get_memory_dir()
    events = list(stream_jsonl(mem / "events.jsonl", limit=limit * 2))
    safety = [
        e
        for e in events
        if e.get("type") in ("policy_violation", "secret_detected", "sandbox_escape_attempt", "rollback_triggered")
    ]
    safety = safety[-limit:]
    severity_counts = Counter(e.get("severity", "unknown") for e in safety)
    return {
        "total": len(safety),
        "severity_counts": dict(severity_counts),
        "events": safety,
    }
