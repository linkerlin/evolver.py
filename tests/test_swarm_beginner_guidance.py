"""Tests for zero-jargon beginner-friendly 3-tool FSM instrument prompt."""

from __future__ import annotations


def test_instrument_presents_three_tool_fsm_for_beginners() -> None:
    """Instrument prompt clearly presents evolve_begin / run_lens / evolve_settle."""
    from evolver.swarm import build_instrument_prompt

    state = {
        "agent_name": "test",
        "workspace_root": "/test",
        "fsm_state": "IDLE",
        "pending_solidify": False,
        "supervision": {"state": "running"},
    }
    prompt = build_instrument_prompt(state)
    assert "evolve_begin" in prompt
    assert "run_lens" in prompt
    assert "evolve_settle" in prompt
    assert "draft_preserved" in prompt
    assert "actionable_fix" in prompt


def test_instrument_free_of_legacy_six_step_jargon() -> None:
    """Instrument prompt never exposes legacy 6-step tools or internal redirect flags."""
    from evolver.swarm import build_instrument_prompt

    prompt = build_instrument_prompt({"agent_name": "test", "workspace_root": "/test"})
    for banned in (
        "swarm_boot",
        "swarm_tick",
        "swarm_distill",
        "swarm_hypothesis",
        "swarm_solidify",
        "swarm_feedback",
        "gate_soft_continue",
        "pending_redirect_loop",
        "loop_fuse",
    ):
        assert banned not in prompt


def test_instrument_reflects_active_run_state() -> None:
    """When FSM is ACTIVE_RUN, prompt directs host to run_lens / evolve_settle."""
    from evolver.swarm import build_instrument_prompt

    prompt = build_instrument_prompt(
        {
            "agent_name": "test",
            "workspace_root": "/test",
            "fsm_state": "ACTIVE_RUN",
            "pending_solidify": True,
        }
    )
    assert "ACTIVE_RUN" in prompt
    assert "下一步：`evolve_settle`" in prompt
