"""Tests for evolver.gep.diagnosis.brief (Sprint B1)."""

from __future__ import annotations

from evolver.gep.diagnosis.brief import (
    render_causal_brief,
    root_cause_signal_keys,
)
from evolver.gep.diagnosis.causal import analyze


def _failed_event(eid: str = "evt_1") -> dict:
    # Two change steps → two stages (indices 0 and 1), matching _GOOD.
    return {
        "id": eid,
        "outcome": {"status": "failed", "score": 0},
        "execution_trace": [
            {"tool": "python", "command_preview": "edit a.py", "error_signature": "timeout"},
            {"tool": "python", "command_preview": "edit b.py"},
        ],
    }


_GOOD = (
    '{"terminal_failure_kind": "agent_timeout", '
    '"stages": ['
    '{"stage_index": 0, "terminal_cause": "test_timeout", '
    '"criticality": "recovered_friction", '
    '"agent_mechanism": "blind_retry", "terminal_link": null}, '
    '{"stage_index": 1, "terminal_cause": "agent_timeout", '
    '"criticality": "root_cause", '
    '"agent_mechanism": "no_progress", "terminal_link": null}'
    '], "root_cause_stage": 1}'
)


class TestRenderCausalBrief:
    def test_empty_analyses_returns_empty(self) -> None:
        assert render_causal_brief([]) == ""

    def test_degraded_analysis_renders(self) -> None:
        analysis = analyze(_failed_event())  # no LLM → degraded
        brief = render_causal_brief([analysis])
        assert "Causal Diagnosis" in brief
        assert "evt_1" in brief
        assert "unattributed" in brief

    def test_attributed_analysis_surfaces_root_cause(self) -> None:
        analysis = analyze(_failed_event(), llm_call=lambda _p: _GOOD)
        brief = render_causal_brief([analysis])
        assert "root_cause" in brief
        assert "agent_timeout" in brief
        assert "no_progress" in brief
        # per-stage lines present
        assert "stage 0" in brief
        assert "stage 1" in brief


class TestRootCauseSignalKeys:
    def test_empty_when_no_root_cause(self) -> None:
        analysis = analyze(_failed_event())  # degraded
        assert root_cause_signal_keys([analysis]) == []

    def test_derives_key(self) -> None:
        analysis = analyze(_failed_event(), llm_call=lambda _p: _GOOD)
        keys = root_cause_signal_keys([analysis])
        assert keys == ["causal:root_cause:agent_timeout"]

    def test_dedups_across_analyses(self) -> None:
        a1 = analyze(_failed_event("e1"), llm_call=lambda _p: _GOOD)
        a2 = analyze(_failed_event("e2"), llm_call=lambda _p: _GOOD)
        keys = root_cause_signal_keys([a1, a2])
        assert keys == ["causal:root_cause:agent_timeout"]
