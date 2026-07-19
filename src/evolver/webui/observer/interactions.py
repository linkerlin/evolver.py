"""Interaction record formatting for WebUI timeline — with run correlation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .jsonl import stream_jsonl
from .redact import redact_text


def format_interactions(
    *, limit: int = 100, memory_dir: Path | None = None
) -> list[dict[str, Any]]:
    """Return recent interaction records, newest first, enriched with run context."""
    from evolver.gep.paths import get_memory_dir

    mem = memory_dir or get_memory_dir()
    events = list(stream_jsonl(mem / "events.jsonl", limit=limit * 2))
    interactions = [
        e for e in events if e.get("type") in ("interaction", "session", "signal", "solidify")
    ]
    interactions = interactions[-limit:]
    interactions.reverse()

    for it in interactions:
        msg = it.get("message") or it.get("summary") or ""
        it["message"] = redact_text(str(msg))
        it["redacted"] = str(msg) != it["message"]
        if "run_id" in it:
            it["has_run"] = True
        if "gene_id" in it:
            it["has_gene"] = True
        if "capsule_id" in it:
            it["has_capsule"] = True
        dur = it.get("duration_ms")
        if isinstance(dur, (int, float)) and dur > 0:
            it["duration_sec"] = round(dur / 1000, 3)

    return interactions
