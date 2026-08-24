"""Sprint 24.2: cycle state machine — stage lattice + timeline projection."""

from __future__ import annotations

from itertools import pairwise

from evolver.gep.cycle_state_machine import (
    STAGE_ABORTED,
    STAGE_FAILED,
    STAGE_GENE_SELECTED,
    STAGE_MUTATION_BUILT,
    STAGE_NONE,
    STAGE_SIGNALS_COLLECTED,
    STAGE_SOLIDIFIED,
    STAGE_STARTED,
    TERMINAL_STAGES,
    advance,
    build_cycle_timeline,
    is_valid_transition,
    stage_for_event,
)


def _evt(etype: str, run_id: str = "r1", **extra: object) -> dict[str, object]:
    return {"type": etype, "run_id": run_id, **extra}


class TestTransitions:
    def test_forward_chain_is_valid(self) -> None:
        chain = [
            STAGE_STARTED,
            STAGE_SIGNALS_COLLECTED,
            STAGE_GENE_SELECTED,
            STAGE_MUTATION_BUILT,
            STAGE_SOLIDIFIED,
        ]
        for before, after in pairwise(chain):
            assert is_valid_transition(before, after)

    def test_regression_invalid(self) -> None:
        assert not is_valid_transition(STAGE_GENE_SELECTED, STAGE_STARTED)
        assert not is_valid_transition(STAGE_SOLIDIFIED, STAGE_MUTATION_BUILT)

    def test_same_stage_invalid(self) -> None:
        assert not is_valid_transition(STAGE_STARTED, STAGE_STARTED)

    def test_unknown_stage_never_advances(self) -> None:
        assert advance(STAGE_NONE, {"type": "totally_unknown"}) == STAGE_NONE


class TestAdvance:
    def test_full_success_path(self) -> None:
        stage = STAGE_NONE
        for evt in (
            _evt("cycle_start"),
            _evt("signals_classified"),
            _evt("gene_selected"),
            _evt("dispatch"),
            _evt("EvolutionEvent", outcome={"status": "success", "score": 1.0}),
        ):
            stage = advance(stage, evt)
        assert stage == STAGE_SOLIDIFIED

    def test_failure_terminal(self) -> None:
        stage = advance(STAGE_MUTATION_BUILT, _evt("EvolutionEvent", outcome={"status": "failed"}))
        assert stage == STAGE_FAILED

    def test_abort_event(self) -> None:
        assert advance(STAGE_STARTED, _evt("cycle_abort")) == STAGE_ABORTED

    def test_monotonic_clamp_on_noise(self) -> None:
        # Out-of-order noise (a late cycle_start after selection) must not
        # rewind the state machine.
        assert advance(STAGE_GENE_SELECTED, _evt("cycle_start")) == STAGE_GENE_SELECTED

    def test_terminal_stage_frozen(self) -> None:
        for terminal in TERMINAL_STAGES:
            assert advance(terminal, _evt("cycle_start")) == terminal


class TestStageForEvent:
    def test_evolution_event_outcome_decides(self) -> None:
        ok = {"type": "EvolutionEvent", "outcome": {"status": "success"}}
        bad = {"type": "EvolutionEvent", "outcome": {"status": "failed"}}
        assert stage_for_event(ok) == STAGE_SOLIDIFIED
        assert stage_for_event(bad) == STAGE_FAILED
        assert stage_for_event({"type": "EvolutionEvent"}) == STAGE_FAILED

    def test_cycle_end_status_decides(self) -> None:
        assert stage_for_event({"type": "cycle_end", "status": "success"}) == STAGE_SOLIDIFIED
        assert stage_for_event({"type": "cycle_end", "status": "error"}) == STAGE_FAILED

    def test_unmapped_and_malformed(self) -> None:
        assert stage_for_event({"type": "llm_review"}) is None
        assert stage_for_event({}) is None


class TestCycleTimeline:
    def test_groups_by_run_in_first_seen_order(self) -> None:
        events = [
            _evt("cycle_start", run_id="r2"),
            _evt("cycle_start", run_id="r1"),
            _evt("EvolutionEvent", run_id="r1", outcome={"status": "success"}),
            _evt("cycle_abort", run_id="r2"),
        ]
        timeline = build_cycle_timeline(events)
        assert [row["run_id"] for row in timeline] == ["r2", "r1"]
        by_run = {row["run_id"]: row for row in timeline}
        assert by_run["r1"]["stage"] == STAGE_SOLIDIFIED
        assert by_run["r1"]["outcome_status"] == "success"
        assert by_run["r2"]["stage"] == STAGE_ABORTED

    def test_stages_seen_records_ladder(self) -> None:
        events = [
            _evt("cycle_start", timestamp="2026-08-24T10:00:00Z"),
            _evt("signals_classified", timestamp="2026-08-24T10:00:01Z"),
            _evt("gene_selected", timestamp="2026-08-24T10:00:02Z"),
        ]
        row = build_cycle_timeline(events)[0]
        assert row["stages_seen"] == [
            STAGE_STARTED,
            STAGE_SIGNALS_COLLECTED,
            STAGE_GENE_SELECTED,
        ]
        assert row["started_at"] and row["ended_at"]

    def test_events_without_run_id_ignored(self) -> None:
        assert build_cycle_timeline([{"type": "cycle_start"}]) == []
