"""Commentary observer — persona-style evolution commentary for WebUI."""

from __future__ import annotations

from typing import Any


def latest_commentary(*, persona: str = "pragmatist", verbose: bool = False) -> dict[str, Any]:
    """Return a single persona commentary for the most recent solidify event."""
    try:
        from evolver.ops.commentary import generate_commentary_for_latest_run

        result = generate_commentary_for_latest_run(verbose=verbose)
        commentaries = result.get("commentaries", {})
        single = commentaries.get(persona, "")
        return {
            "event_id": result.get("event_id"),
            "gene_id": result.get("gene_id"),
            "timestamp": result.get("timestamp"),
            "persona": persona,
            "commentary": single,
            "commentaries": {persona: single},
        }
    except Exception as exc:
        return {"error": str(exc), "commentaries": {}}


def latest_all_commentaries(*, verbose: bool = False) -> dict[str, Any]:
    """Return all three persona commentaries for the latest run."""
    try:
        from evolver.ops.commentary import generate_commentary_for_latest_run

        return generate_commentary_for_latest_run(verbose=verbose)
    except Exception as exc:
        return {"error": str(exc), "commentaries": {}}
