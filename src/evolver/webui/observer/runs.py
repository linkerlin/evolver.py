"""Evolution run history statistics for WebUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .jsonl import stream_jsonl


def runs_history(*, limit: int = 50, memory_dir: Path | None = None) -> dict[str, Any]:
    """Return run-level statistics."""
    from evolver.gep.paths import get_memory_dir

    mem = memory_dir or get_memory_dir()
    events = list(stream_jsonl(mem / "events.jsonl"))

    cycles = [e for e in events if e.get("type") == "cycle_end"]
    total = len(cycles)
    successes = sum(1 for c in cycles if c.get("outcome") == "success")
    failures = total - successes
    rate = successes / total if total else 0.0

    recent = cycles[-limit:]
    recent.reverse()

    return {
        "total_cycles": total,
        "successes": successes,
        "failures": failures,
        "success_rate": round(rate, 3),
        "recent": [{"ts": c.get("timestamp"), "outcome": c.get("outcome"), "gene_id": c.get("gene_id")} for c in recent],
    }
