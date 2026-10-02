"""Tests for evolver.gep.record_route (经验即证据 §5.6, shadow).

The dual-direction record route: two qualitative directions run in parallel,
each producing a content-addressed record, each direction's context including
the other's record. No scoring, archive kept.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep import record_route


@pytest.fixture
def route_env(temp_workspace: Path) -> Path:
    return temp_workspace


def _scene(run_id: str, event_id: str) -> dict[str, object]:
    return {
        "event": {
            "type": "EvolutionEvent",
            "id": event_id,
            "run_id": run_id,
            "timestamp": "2026-10-02T00:00:00.000Z",
            "gene_id": "gene_a",
            "mutation": {"id": "mut_1", "category": "repair"},
            "diff_snapshot": f"+# {run_id}\n",
            "outcome": {"status": "success", "score": 1.0},
        },
        "validation_result": {"ok": True, "results": []},
        "fitness_verdict": None,
        "gate": {"accepted": True},
    }


def test_two_directions_each_produce_a_record(route_env: Path) -> None:
    result = record_route.run_dual_record_route(
        _scene("run_cap", "evt_cap"), _scene("run_adp", "evt_adp")
    )
    assert result["capability_record"]["ok"] is True
    assert result["adaptive_record"]["ok"] is True
    assert result["capability_record"]["id"] != result["adaptive_record"]["id"]


def test_each_direction_sees_the_others_record(route_env: Path) -> None:
    """判据: 两路线各出记录且互见对方记录."""
    result = record_route.run_dual_record_route(
        _scene("run_cap", "evt_cap"), _scene("run_adp", "evt_adp")
    )
    # capability's context cites the adaptive record, and vice versa
    assert result["adaptive_record"]["id"] in result["capability_context"]
    assert result["capability_record"]["id"] in result["adaptive_context"]
    # and each cites its own
    assert result["capability_record"]["id"] in result["capability_context"]
    assert result["adaptive_record"]["id"] in result["adaptive_context"]


def test_directions_are_capability_and_adaptive() -> None:
    assert record_route.DIRECTIONS == ("capability", "adaptive")
    assert record_route.other_direction("capability") == "adaptive"
    assert record_route.other_direction("adaptive") == "capability"
    with pytest.raises(ValueError):
        record_route.other_direction("sideways")


def test_records_are_kept_not_scored(route_env: Path) -> None:
    """Archive keeps both — no winner is chosen, both records persist."""
    result = record_route.run_dual_record_route(
        _scene("run_cap", "evt_cap"), _scene("run_adp", "evt_adp")
    )
    from evolver.gep import episode_record

    entries = episode_record.list_episodes()
    ids = {entry["id"] for entry in entries}
    assert result["capability_record"]["id"] in ids
    assert result["adaptive_record"]["id"] in ids
