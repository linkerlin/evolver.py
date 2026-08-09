"""Tests for evolver.gep.diagnosis.causal (Sprint B1)."""

from __future__ import annotations

import json

import pytest

from evolver.gep.diagnosis.causal import (
    CausalAnalysisError,
    analyze,
    build_analysis_prompt,
    pick_root_cause,
)
from evolver.gep.diagnosis.trace import build_stage_records, normalize_trace_steps


def _failed_event(*, with_change: bool = True) -> dict:
    """A synthetic failed event with a 2-stage trace (change splits stages)."""
    trace = [
        {"tool": "pytest", "command_preview": "pytest -q", "error_signature": "timeout expired"},
    ]
    if with_change:
        trace.append({"tool": "python", "command_preview": "edit foo.py"})
    trace.append({"tool": "ruff", "command_preview": "ruff check", "error_signature": "E501"})
    return {
        "id": "evt_99",
        "outcome": {"status": "failed", "score": 0},
        "signals": ["log_error"],
        "execution_trace": trace,
    }


def _good_response(*, root_stage: int | None = 1) -> str:
    return json.dumps(
        {
            "terminal_failure_kind": "agent_timeout",
            "stages": [
                {
                    "stage_index": 0,
                    "terminal_cause": "test_timeout",
                    "criticality": "recovered_friction",
                    "agent_mechanism": "blind_retry",
                    "terminal_link": None,
                },
                {
                    "stage_index": 1,
                    "terminal_cause": "agent_timeout",
                    "criticality": "root_cause",
                    "agent_mechanism": "no_progress_guard",
                    "terminal_link": "stage 0 timeout recurred",
                },
            ],
            "root_cause_stage": root_stage,
        }
    )


class TestAnalyzeDegraded:
    def test_no_llm_call_returns_unknown_attribution(self) -> None:
        analysis = analyze(_failed_event())
        assert analysis.event_id == "evt_99"
        assert analysis.terminal_failure_kind == "agent_timeout"  # deterministic hint
        assert len(analysis.stages) == 2
        assert all(s.criticality == "unknown" for s in analysis.stages)
        assert analysis.root_cause_stage is None

    def test_no_llm_call_with_empty_trace(self) -> None:
        analysis = analyze({"id": "evt_x", "execution_trace": []})
        assert analysis.stages == []
        assert analysis.terminal_failure_kind == "unknown"


class TestAnalyzeWithLlm:
    def test_valid_response_fills_attribution(self) -> None:
        analysis = analyze(_failed_event(), llm_call=lambda _p: _good_response())
        assert analysis.terminal_failure_kind == "agent_timeout"
        assert len(analysis.stages) == 2
        assert analysis.stages[0].criticality == "recovered_friction"
        assert analysis.stages[1].criticality == "root_cause"
        assert analysis.stages[1].terminal_cause == "agent_timeout"
        assert analysis.stages[1].agent_mechanism == "no_progress_guard"
        assert analysis.root_cause_stage == 1

    def test_root_cause_inferred_when_omitted(self) -> None:
        resp = _good_response(root_stage=None)
        # remove root_cause_stage key entirely
        resp_dict = json.loads(resp)
        del resp_dict["root_cause_stage"]
        analysis = analyze(_failed_event(), llm_call=lambda _p: json.dumps(resp_dict))
        # stage 1 is the only root_cause → inferred
        assert analysis.root_cause_stage == 1

    def test_fenced_json_parsed(self) -> None:
        fenced = "```json\n" + _good_response() + "\n```"
        analysis = analyze(_failed_event(), llm_call=lambda _p: fenced)
        assert analysis.stages[1].criticality == "root_cause"

    def test_bare_json_in_prose_parsed(self) -> None:
        prose = "Here is my analysis:\n" + _good_response() + "\nThanks."
        analysis = analyze(_failed_event(), llm_call=lambda _p: prose)
        assert analysis.stages[1].terminal_cause == "agent_timeout"

    def test_terminal_kind_overrides_hint(self) -> None:
        resp = json.loads(_good_response())
        resp["terminal_failure_kind"] = "verifier_assertion"
        analysis = analyze(_failed_event(), llm_call=lambda _p: json.dumps(resp))
        assert analysis.terminal_failure_kind == "verifier_assertion"

    def test_invalid_terminal_kind_ignored_keeps_hint(self) -> None:
        resp = json.loads(_good_response())
        resp["terminal_failure_kind"] = "totally_bogus"
        analysis = analyze(_failed_event(), llm_call=lambda _p: json.dumps(resp))
        assert analysis.terminal_failure_kind == "agent_timeout"  # kept hint


class TestAnalyzeStrictValidation:
    def test_empty_response_raises(self) -> None:
        with pytest.raises(CausalAnalysisError):
            analyze(_failed_event(), llm_call=lambda _p: "   ")

    def test_non_object_json_raises(self) -> None:
        with pytest.raises(CausalAnalysisError):
            analyze(_failed_event(), llm_call=lambda _p: "[1,2,3]")

    def test_no_json_raises(self) -> None:
        with pytest.raises(CausalAnalysisError):
            analyze(_failed_event(), llm_call=lambda _p: "no json here at all")

    def test_missing_stages_raises(self) -> None:
        with pytest.raises(CausalAnalysisError):
            resp = '{"terminal_failure_kind": "agent_timeout"}'
            analyze(_failed_event(), llm_call=lambda _p: resp)

    def test_invalid_criticality_raises(self) -> None:
        resp = json.loads(_good_response())
        resp["stages"][0]["criticality"] = "definitely_wrong"
        with pytest.raises(CausalAnalysisError, match="invalid criticality"):
            analyze(_failed_event(), llm_call=lambda _p: json.dumps(resp))

    def test_non_snake_case_token_raises(self) -> None:
        resp = json.loads(_good_response())
        resp["stages"][0]["terminal_cause"] = "BadToken"
        with pytest.raises(CausalAnalysisError, match="not snake_case"):
            analyze(_failed_event(), llm_call=lambda _p: json.dumps(resp))

    def test_missing_terminal_cause_raises(self) -> None:
        resp = json.loads(_good_response())
        del resp["stages"][0]["terminal_cause"]
        with pytest.raises(CausalAnalysisError, match="missing terminal_cause"):
            analyze(_failed_event(), llm_call=lambda _p: json.dumps(resp))

    def test_stage_index_mismatch_raises(self) -> None:
        resp = json.loads(_good_response())
        resp["stages"][1]["stage_index"] = 5  # not in {0,1}
        with pytest.raises(CausalAnalysisError, match="stage_index mismatch"):
            analyze(_failed_event(), llm_call=lambda _p: json.dumps(resp))

    def test_duplicate_stage_index_raises(self) -> None:
        resp = json.loads(_good_response())
        resp["stages"][1]["stage_index"] = 0  # collide with stage 0
        with pytest.raises(CausalAnalysisError, match="duplicate stage_index"):
            analyze(_failed_event(), llm_call=lambda _p: json.dumps(resp))


class TestBuildAnalysisPrompt:
    def test_prompt_contains_contract(self) -> None:
        event = _failed_event()
        steps = normalize_trace_steps(event)
        stages = build_stage_records(steps)
        prompt = build_analysis_prompt(stages, "agent_timeout", event_id="evt_99")
        assert "root_cause" in prompt
        assert "stage_index" in prompt
        assert "evt_99" in prompt
        assert "agent_timeout" in prompt


class TestPickRootCause:
    def test_returns_root_cause_tuple(self) -> None:
        analysis = analyze(_failed_event(), llm_call=lambda _p: _good_response())
        rc = pick_root_cause(analysis)
        assert rc == ("root_cause", "agent_timeout", "no_progress_guard")

    def test_none_when_no_root_cause(self) -> None:
        analysis = analyze(_failed_event())  # degraded, all unknown
        assert pick_root_cause(analysis) is None
