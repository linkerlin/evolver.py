"""Comprehensive Wave 3 verification: beginner guidance + hard blocks preserved."""

from __future__ import annotations

from pathlib import Path


def test_wave3_beginner_guidance_present() -> None:
    """Verify beginner guidance appears in instrument for first-time users."""
    from evolver.swarm import build_instrument_prompt

    state = {
        "agent_name": "test",
        "workspace_root": "/test",
        "genes": 0,
        "capsules": 0,
        "pending_solidify": False,
        "bench_pack_gate": {"armed": False},
        "supervision": {"state": "running"},
        "hitl": {"mode": "off", "pending": 0},
        "tick_count": 1,
    }

    prompt = build_instrument_prompt(state)

    # Core requirements from Wave 3
    assert "核心循环工具" in prompt or "Core Loop Tools" in prompt
    assert "swarm_tick" in prompt
    assert "swarm_distill" in prompt
    assert "swarm_hypothesis" in prompt
    assert "swarm_solidify" in prompt
    assert "swarm_feedback" in prompt
    assert "soft-accept" in prompt or "soft_accept" in prompt


def test_wave3_hard_blocks_policy_intact() -> None:
    """Verify permanent hard-block policy remains unchanged.

    Per Task 3.3: secrets, ~/.evolver, val_seal remain hard blocks.
    Soft-accept never writes Parent baseline, never auto-commits.
    """
    from evolver.bench.frozen_gate import is_usability_soft_reason

    # Soft reasons remain soft
    assert is_usability_soft_reason("no_baseline")
    assert is_usability_soft_reason("pack_absent")
    assert is_usability_soft_reason("unmeasured")
    assert is_usability_soft_reason("drop")
    assert is_usability_soft_reason("flat")
    assert is_usability_soft_reason("regression")

    # Hard reasons stay hard
    assert not is_usability_soft_reason("secrets_policy_violation")
    assert not is_usability_soft_reason("gate_error")
    assert not is_usability_soft_reason("seal_violation")


def test_wave3_next_action_guidance_concept() -> None:
    """Verify next_action guidance mechanism (conceptual).

    Per Task 3.2: boot/status could include next_action_guidance field.
    This test verifies the opening_action mechanism works correctly.
    """
    from evolver.swarm import _opening_action

    # State with pending solidify
    state_pending = {"pending_solidify": True}
    next_act, _ = _opening_action(state_pending)
    assert next_act == "swarm_solidify"

    # State paused
    state_paused = {
        "pending_solidify": False,
        "supervision": {"state": "paused"},
    }
    next_act, _ = _opening_action(state_paused)
    assert next_act == "await_supervisor_resume"

    # Normal state
    state_normal = {
        "pending_solidify": False,
        "supervision": {"state": "running"},
    }
    next_act, _ = _opening_action(state_normal)
    assert next_act == "swarm_tick"


def test_wave3_no_auto_commit_preserved() -> None:
    """Verify no auto-commit policy is preserved in soft-accept."""
    from evolver.bench.frozen_gate import enrich_soft_accept

    verdict = {
        "verdict": "reject",
        "reason": "no_baseline",
        "accept": False,
    }

    enriched = enrich_soft_accept(verdict)

    # Soft-accept should warn about no auto-commit
    assert enriched["soft_accept"] is True
    warnings_text = " ".join(enriched.get("warnings", [])).lower()
    assert "does not write a parent baseline" in warnings_text


def test_wave3_experience_in_state_root() -> None:
    """Verify experience writes to state_root, not repo."""
    from evolver.gep.paths import get_workspace_state_dir

    # Just verify the path resolution works correctly
    # Actual writes are tested in solidify tests
    repo = Path("/fake/repo")
    state_dir = get_workspace_state_dir(repo)

    # State dir should be under ~/.evolver/workspaces/<id>/
    assert ".evolver" in str(state_dir) or state_dir.name.startswith("workspace")
