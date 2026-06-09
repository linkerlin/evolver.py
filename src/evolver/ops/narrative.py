"""Narrative and reflection log generation.

Equivalent to evolver/src/ops/narrative.js.
Generates human-readable evolution narrative and structured reflections
after each solidify cycle.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from evolver.gep.asset_store import append_jsonl
from evolver.gep.paths import get_evolution_dir, get_narrative_path, get_reflection_log_path


def _format_blast_radius(br: dict[str, Any]) -> str:
    files = br.get("files", 0)
    lines = br.get("lines", 0)
    if files == 0 and lines == 0:
        return "no file changes"
    return f"{files} file(s), {lines} line(s) changed"


def generate_narrative(event: dict[str, Any]) -> str:
    """Generate a markdown narrative entry for a single evolution event."""
    ts = event.get("timestamp", "?")
    gene_id = event.get("gene_id", "unknown")
    signals = event.get("signals", [])
    mutation = event.get("mutation") or {}
    blast_radius = event.get("blast_radius", {})
    outcome = event.get("outcome") or {}
    status = outcome.get("status", "unknown")
    score = outcome.get("score", "?")

    lines: list[str] = [
        f"## Evolution at {ts}",
        "",
        f"- **Gene**: `{gene_id}`",
        f"- **Signals**: {', '.join(str(s) for s in signals[:5])}",
        f"- **Mutation**: {mutation.get('id', '?')} ({mutation.get('category', '?')})",
        f"- **Risk**: {mutation.get('risk_level', '?')}",
        f"- **Blast radius**: {_format_blast_radius(blast_radius)}",
        f"- **Outcome**: {status} (score={score})",
        "",
    ]
    return "\n".join(lines)


def append_narrative(event: dict[str, Any]) -> None:
    """Append a narrative entry to the evolution narrative file."""
    path = get_narrative_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = generate_narrative(event)
    with open(path, "a", encoding="utf-8") as f:
        f.write(entry + "\n")


def generate_reflection(event: dict[str, Any]) -> dict[str, Any]:
    """Generate a structured reflection record."""
    outcome = event.get("outcome") or {}
    mutation = event.get("mutation") or {}
    blast_radius = event.get("blast_radius", {})
    signals = event.get("signals", [])

    reflection: dict[str, Any] = {
        "type": "Reflection",
        "timestamp": event.get("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        "event_id": event.get("id"),
        "gene_id": event.get("gene_id"),
        "mutation_category": mutation.get("category"),
        "outcome_status": outcome.get("status"),
        "outcome_score": outcome.get("score"),
        "blast_radius": blast_radius,
        "signals": signals,
        # Simple heuristics
        "reflection": _compute_reflection_text(outcome, blast_radius),
        "lessons": _extract_lessons(event),
    }
    return reflection


def _compute_reflection_text(outcome: dict, blast_radius: dict) -> str:
    status = outcome.get("status", "")
    files = blast_radius.get("files", 0)
    if status == "success" and files <= 3:
        return "Clean, low-blast success — strategy validated."
    if status == "success" and files > 10:
        return "Success but large blast radius — consider splitting future mutations."
    if status == "failed":
        return "Failed cycle — need stronger validation or smaller scope."
    return "Cycle completed."


def _extract_lessons(event: dict[str, Any]) -> list[str]:
    lessons: list[str] = []
    outcome = event.get("outcome") or {}
    mutation = event.get("mutation") or {}
    if outcome.get("status") == "failed":
        lessons.append("validation_failed")
    if (event.get("blast_radius") or {}).get("files", 0) > 10:
        lessons.append("large_blast_radius")
    if mutation.get("category") == "innovate" and outcome.get("status") == "success":
        lessons.append("innovation_worked")
    return lessons


def append_reflection(event: dict[str, Any]) -> None:
    """Append a structured reflection to the reflection log."""
    reflection = generate_reflection(event)
    path = get_reflection_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl(path, reflection)


def record_narrative_and_reflection(event: dict[str, Any]) -> dict[str, Any]:
    """High-level helper: append both narrative and reflection for an event."""
    try:
        append_narrative(event)
    except Exception as exc:
        return {"ok": False, "error": f"narrative_failed: {exc}"}
    try:
        append_reflection(event)
    except Exception as exc:
        return {"ok": False, "error": f"reflection_failed: {exc}"}
    return {"ok": True}
