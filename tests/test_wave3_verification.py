"""Comprehensive Wave 3 / v1.114.0 verification: 3-tool FSM guidance + hard blocks preserved."""

from __future__ import annotations

from pathlib import Path


def test_wave3_fsm_guidance_present() -> None:
    """Verify concise 3-tool FSM guidance appears in instrument for first-time users."""
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


def test_wave3_hard_blocks_policy_intact() -> None:
    """Verify permanent hard-block policy remains unchanged."""
    from evolver.bench.frozen_gate import is_usability_soft_reason

    # First-run environment gaps remain soft (auto-filled by `evolver init`)
    assert is_usability_soft_reason("no_baseline")
    assert is_usability_soft_reason("pack_absent")
    assert is_usability_soft_reason("unmeasured")

    # Fitness verdicts are honest rejects since v1.114.0
    assert not is_usability_soft_reason("drop")
    assert not is_usability_soft_reason("flat")
    assert not is_usability_soft_reason("regression")

    # Hard reasons stay hard
    assert not is_usability_soft_reason("secrets_policy_violation")
    assert not is_usability_soft_reason("gate_error")
    assert not is_usability_soft_reason("seal_violation")


def test_wave3_next_action_guidance_concept() -> None:
    """Verify _opening_action maps FSM states cleanly."""
    from evolver.swarm import _opening_action

    state_pending = {"pending_solidify": True, "fsm_state": "ACTIVE_RUN"}
    next_act, _ = _opening_action(state_pending)
    assert next_act == "evolve_settle"

    state_paused = {
        "pending_solidify": False,
        "fsm_state": "IDLE",
        "supervision": {"state": "paused"},
    }
    next_act, _ = _opening_action(state_paused)
    assert next_act == "await_supervisor_resume"

    state_normal = {
        "pending_solidify": False,
        "fsm_state": "IDLE",
        "supervision": {"state": "running"},
    }
    next_act, _ = _opening_action(state_normal)
    assert next_act == "evolve_begin"


def test_wave3_no_auto_commit_preserved() -> None:
    """Verify no auto-commit policy is preserved in soft-accept."""
    from evolver.bench.frozen_gate import enrich_soft_accept

    verdict = {
        "verdict": "reject",
        "reason": "no_baseline",
        "accept": False,
    }

    enriched = enrich_soft_accept(verdict)
    assert enriched["soft_accept"] is True
    warnings_text = " ".join(enriched.get("warnings", [])).lower()
    assert "does not write a parent baseline" in warnings_text


def test_wave3_experience_in_state_root() -> None:
    """Verify experience writes to state_root, not repo."""
    from evolver.gep.paths import get_workspace_state_dir

    repo = Path("/fake/repo")
    state_dir = get_workspace_state_dir(repo)
    assert ".evolver" in str(state_dir) or state_dir.name.startswith("workspace")
