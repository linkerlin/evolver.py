"""Tests for evolver.gep.diagnosis.schemas (Sprint B1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from evolver.gep.diagnosis.schemas import (
    CRITICALITY_RANK,
    CausalAnalysis,
    NormalizedStep,
    StageRecord,
    is_signature_token,
)


class TestNormalizedStep:
    def test_minimal_with_index(self) -> None:
        step = NormalizedStep(index=0)
        assert step.index == 0
        assert step.tool == ""
        assert step.is_change is False
        assert step.summary == ""

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            NormalizedStep(index=0, bogus=True)  # type: ignore[call-arg]

    def test_full(self) -> None:
        step = NormalizedStep(index=2, tool="edit", is_change=True, summary="fix")
        assert step.is_change is True


class TestStageRecord:
    def test_defaults_unknown_attribution(self) -> None:
        stage = StageRecord(stage_index=0)
        assert stage.criticality == "unknown"
        assert stage.terminal_cause == ""
        assert stage.agent_mechanism == ""

    def test_valid_criticality(self) -> None:
        stage = StageRecord(stage_index=0, criticality="root_cause")
        assert stage.criticality == "root_cause"

    def test_invalid_criticality_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StageRecord(stage_index=0, criticality="definitely_a_bug")  # type: ignore[arg-type]

    def test_signature_token_must_be_snake_case(self) -> None:
        # empty allowed (pre-analysis)
        StageRecord(stage_index=0, terminal_cause="")
        StageRecord(stage_index=0, agent_mechanism="")
        # valid tokens
        StageRecord(stage_index=0, terminal_cause="missing_required_artifact")
        StageRecord(stage_index=0, agent_mechanism="retry_after_timeout")
        # invalid: uppercase / spaces / leading digit
        with pytest.raises(ValidationError):
            StageRecord(stage_index=0, terminal_cause="BadToken")
        with pytest.raises(ValidationError):
            StageRecord(stage_index=0, agent_mechanism="has space")
        with pytest.raises(ValidationError):
            StageRecord(stage_index=0, terminal_cause="1leading_digit")


class TestCausalAnalysis:
    def test_minimal(self) -> None:
        analysis = CausalAnalysis(event_id="evt_1")
        assert analysis.event_id == "evt_1"
        assert analysis.terminal_failure_kind == "unknown"
        assert analysis.stages == []
        assert analysis.root_cause_stage is None
        assert analysis.format == "evolver.diagnosis.v0"

    def test_invalid_terminal_failure_kind(self) -> None:
        with pytest.raises(ValidationError):
            CausalAnalysis(event_id="evt_1", terminal_failure_kind="boom")  # type: ignore[arg-type]

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            CausalAnalysis(event_id="evt_1", surprise=True)  # type: ignore[call-arg]

    def test_round_trip_with_stages(self) -> None:
        analysis = CausalAnalysis(
            event_id="evt_42",
            terminal_failure_kind="agent_timeout",
            root_cause_stage=1,
            stages=[
                StageRecord(
                    stage_index=0,
                    steps=[NormalizedStep(index=0, tool="ls")],
                    terminal_cause="exploration_ok",
                    criticality="recovered_friction",
                    agent_mechanism="blind_retry",
                ),
                StageRecord(
                    stage_index=1,
                    steps=[NormalizedStep(index=1, tool="edit", is_change=True)],
                    terminal_cause="agent_timeout",
                    criticality="root_cause",
                    agent_mechanism="no_progress_guard",
                ),
            ],
        )
        dumped = analysis.model_dump()
        rebuilt = CausalAnalysis.model_validate(dumped)
        assert rebuilt.root_cause_stage == 1
        assert rebuilt.stages[1].criticality == "root_cause"


class TestCriticalityRank:
    def test_root_cause_ranks_first(self) -> None:
        # ascending rank → root_cause is the smallest (sorted first)
        assert CRITICALITY_RANK["root_cause"] == 0
        assert CRITICALITY_RANK["unknown"] == 4
        ranked = sorted(CRITICALITY_RANK, key=lambda k: CRITICALITY_RANK[k])
        assert ranked[0] == "root_cause"
        assert ranked[-1] == "unknown"


class TestIsSignatureToken:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("missing_required_artifact", True),
            ("retry_after_timeout", True),
            ("a", True),
            ("", False),
            ("Bad", False),
            ("has space", False),
            ("1digit", False),
            ("dash-not", False),
        ],
    )
    def test_cases(self, value: str, expected: bool) -> None:
        assert is_signature_token(value) is expected
