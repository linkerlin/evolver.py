"""Sprint 24.1: event projection — replay-derived views (概念收割 #3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep import mutation as mutation_mod
from evolver.gep.event_projection import (
    load_projections,
    project_events,
    rebuild_projections,
    scored_category_window,
)


def _evt(
    run_id: str,
    *,
    gene_id: str | None = "gene_a",
    category: str | None = "repair",
    status: str = "success",
    score: float | None = 1.0,
) -> dict[str, object]:
    outcome: dict[str, object] = {"status": status}
    if score is not None:
        outcome["score"] = score
    evt: dict[str, object] = {
        "type": "EvolutionEvent",
        "id": f"evt_{run_id}",
        "run_id": run_id,
        "timestamp": f"2026-08-24T00:00:{len(run_id):02d}Z",
        "gene_id": gene_id,
        "outcome": outcome,
    }
    if category is not None:
        evt["mutation"] = {"category": category}
    return evt


class TestProjectEvents:
    def test_gene_outcomes_tallies(self) -> None:
        views = project_events(
            [
                _evt("r1"),
                _evt("r2", status="failed", score=0.0),
                _evt("r3", gene_id="gene_b"),
                {"type": "cycle_end", "run_id": "r4"},  # ignored
            ]
        )
        genes = views["gene_outcomes"]
        assert genes["gene_a"]["attempts"] == 2
        assert genes["gene_a"]["successes"] == 1
        assert genes["gene_a"]["failures"] == 1
        assert genes["gene_a"]["score_sum"] == pytest.approx(1.0)
        assert genes["gene_b"]["attempts"] == 1
        assert views["event_count"] == 4

    def test_scored_categories_preserves_order_and_filter(self) -> None:
        views = project_events(
            [
                _evt("r1", category="repair", score=1.0),
                _evt("r2", category=None, score=1.0),  # no category → filtered
                _evt("r3", category="innovate", score=0.5),
                _evt("r4", category="repair", score=None),  # non-numeric → filtered
            ]
        )
        pairs = [(p["category"], p["score"]) for p in views["scored_categories"]]
        assert pairs == [("repair", 1.0), ("innovate", 0.5)]
        totals = views["category_totals"]
        assert totals["repair"] == {"attempts": 1.0, "score_sum": 1.0}

    def test_timeline_view_present(self) -> None:
        views = project_events([_evt("r1"), _evt("r2", status="failed")])
        timeline = views["cycle_timeline"]
        assert [row["run_id"] for row in timeline] == ["r1", "r2"]
        assert timeline[0]["stage"] == "solidified"
        assert timeline[1]["stage"] == "failed"


class TestRebuildRoundTrip:
    def test_rebuild_and_load(self, temp_workspace: Path) -> None:
        from evolver.gep.asset_store import append_event_jsonl

        append_event_jsonl(_evt("r1"))
        append_event_jsonl({"type": "noise"})
        views = rebuild_projections()
        assert views["event_count"] == 2

        loaded = load_projections()
        assert loaded is not None
        assert loaded["event_count"] == 2
        assert loaded["gene_outcomes"]["gene_a"]["attempts"] == 1

    def test_load_missing_returns_none(self, temp_workspace: Path) -> None:
        assert load_projections() is None


class TestOperatorBanditWiring:
    def test_window_matches_inline_scan(self, temp_workspace: Path) -> None:
        """Projection path must be byte-equivalent with the historical scan."""
        from evolver.gep.asset_store import append_event_jsonl
        from evolver.gep.feature_flags import invalidate_cache

        append_event_jsonl(_evt("r1", category="repair", score=1.0))
        append_event_jsonl(_evt("r2", category="optimize", score=0.25))
        append_event_jsonl(_evt("r3", category="repair", score=0.5))

        invalidate_cache()
        stats = scored_category_window(window=50)
        assert stats["repair"] == {"attempts": 2.0, "score_sum": 1.5}
        assert stats["optimize"] == {"attempts": 1.0, "score_sum": 0.25}

        # Flag-gated consumer path returns identical aggregates.
        from evolver.gep.feature_flags import set_flag

        try:
            set_flag("enable_event_projection", True)
            invalidate_cache()
            assert mutation_mod._category_stats() == stats
        finally:
            set_flag("enable_event_projection", False)
            invalidate_cache()
