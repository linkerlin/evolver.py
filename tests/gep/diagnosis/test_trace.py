"""Tests for evolver.gep.diagnosis.trace (Sprint B1)."""

from __future__ import annotations

from evolver.gep.diagnosis.trace import (
    build_stage_records,
    classify_terminal_failure,
    normalize_trace_steps,
)


def _entry(tool: str = "", cmd: str = "", err: str = "", files: int | None = None) -> dict:
    entry: dict = {"tool": tool, "command_preview": cmd}
    if err:
        entry["error_signature"] = err
    if files is not None:
        entry["files_touched"] = files
    return entry


class TestNormalizeTraceSteps:
    def test_missing_trace_returns_empty(self) -> None:
        assert normalize_trace_steps({}) == []
        assert normalize_trace_steps({"execution_trace": None}) == []

    def test_empty_trace(self) -> None:
        assert normalize_trace_steps({"execution_trace": []}) == []

    def test_basic_normalization(self) -> None:
        event = {
            "execution_trace": [
                _entry(tool="pytest", cmd="pytest -q"),
                _entry(tool="ruff", cmd="ruff check src", err="E501 line too long"),
            ]
        }
        steps = normalize_trace_steps(event)
        assert len(steps) == 2
        assert steps[0].index == 0
        assert steps[0].tool == "pytest"
        assert steps[0].is_change is False  # pytest is not a write
        # error_signature preferred over command_preview
        assert steps[1].summary == "E501 line too long"

    def test_change_detected_by_command_verb(self) -> None:
        event = {
            "execution_trace": [
                _entry(tool="python", cmd="python apply_patch.py"),
            ]
        }
        steps = normalize_trace_steps(event)
        assert steps[0].is_change is True

    def test_change_detected_by_files_touched(self) -> None:
        event = {
            "execution_trace": [
                _entry(tool="git", cmd="git status", files=3),
            ]
        }
        steps = normalize_trace_steps(event)
        assert steps[0].is_change is True

    def test_non_dict_entries_skipped(self) -> None:
        event = {"execution_trace": ["not-a-dict", _entry(cmd="pytest")]}
        steps = normalize_trace_steps(event)
        assert len(steps) == 1
        assert steps[0].index == 0  # re-indexed, not original position


class TestBuildStageRecords:
    def test_empty_steps(self) -> None:
        assert build_stage_records([]) == []

    def test_no_change_step_yields_single_stage(self) -> None:
        steps = normalize_trace_steps(
            {"execution_trace": [_entry(cmd="pytest"), _entry(cmd="ruff")]}
        )
        stages = build_stage_records(steps)
        assert len(stages) == 1
        assert stages[0].stage_index == 0
        assert len(stages[0].steps) == 2
        # attribution defaults untouched
        assert stages[0].criticality == "unknown"
        assert stages[0].terminal_cause == ""

    def test_change_step_splits_stages(self) -> None:
        steps = normalize_trace_steps(
            {
                "execution_trace": [
                    _entry(cmd="pytest"),  # stage 0 (no change) → stays open
                    _entry(cmd="edit foo.py"),  # change → closes stage 0
                    _entry(cmd="pytest"),  # stage 1, open
                    _entry(cmd="write bar.py"),  # change → closes stage 1
                    _entry(cmd="ruff check"),  # stage 2, final partial
                ]
            }
        )
        stages = build_stage_records(steps)
        assert len(stages) == 3
        assert [len(s.steps) for s in stages] == [2, 2, 1]
        assert [s.stage_index for s in stages] == [0, 1, 2]

    def test_consecutive_change_steps_each_close(self) -> None:
        steps = normalize_trace_steps(
            {
                "execution_trace": [
                    _entry(cmd="edit a.py"),  # change → stage 0 (single)
                    _entry(cmd="edit b.py"),  # change → stage 1 (single)
                ]
            }
        )
        stages = build_stage_records(steps)
        assert len(stages) == 2
        assert all(len(s.steps) == 1 for s in stages)

    def test_summary_joined(self) -> None:
        steps = normalize_trace_steps(
            {
                "execution_trace": [
                    _entry(cmd="pytest", err="ERR1"),
                    _entry(cmd="edit x.py"),
                ]
            }
        )
        stages = build_stage_records(steps)
        assert "ERR1" in stages[0].summary


class TestClassifyTerminalFailure:
    def test_no_signal_unknown(self) -> None:
        assert classify_terminal_failure({}) == "unknown"

    def test_timeout(self) -> None:
        ev = {"execution_trace": [_entry(err="subprocess timeout expired")]}
        assert classify_terminal_failure(ev) == "agent_timeout"

    def test_missing_dependency(self) -> None:
        ev = {"execution_trace": [_entry(err="ModuleNotFoundError: foo")]}
        assert classify_terminal_failure(ev) == "missing_dependency"

    def test_missing_artifact(self) -> None:
        ev = {"execution_trace": [_entry(err="FileNotFoundError: out.txt")]}
        assert classify_terminal_failure(ev) == "missing_required_artifact"

    def test_assertion(self) -> None:
        ev = {"execution_trace": [_entry(err="AssertionError: bad")]}
        assert classify_terminal_failure(ev) == "verifier_assertion"

    def test_reward_zero_fallback(self) -> None:
        ev = {"outcome": {"status": "failed", "score": 0}}
        assert classify_terminal_failure(ev) == "reward_zero"

    def test_sharper_pattern_wins_over_reward_zero(self) -> None:
        ev = {
            "outcome": {"status": "failed", "score": 0},
            "execution_trace": [_entry(err="timeout")],
        }
        assert classify_terminal_failure(ev) == "agent_timeout"
