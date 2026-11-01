"""Tests for beginner guidance in swarm instrument/boot."""

from __future__ import annotations


def test_instrument_includes_core_loop_tools_for_beginners() -> None:
    """Instrument prompt includes Core Loop Tools section for low tick counts."""
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
        "tick_count": 2,  # Low tick count
    }

    prompt = build_instrument_prompt(state)

    # Should include beginner guidance
    assert "核心循环工具" in prompt or "Core Loop Tools" in prompt
    assert "swarm_tick" in prompt
    assert "swarm_distill" in prompt
    assert "swarm_hypothesis" in prompt
    assert "swarm_solidify" in prompt
    assert "swarm_feedback" in prompt


def test_instrument_no_beginner_guidance_for_experienced() -> None:
    """Instrument prompt does not include beginner section after 5+ ticks."""
    from evolver.swarm import build_instrument_prompt

    state = {
        "agent_name": "test",
        "workspace_root": "/test",
        "genes": 5,
        "capsules": 3,
        "pending_solidify": False,
        "bench_pack_gate": {"armed": True},
        "supervision": {"state": "running"},
        "hitl": {"mode": "off", "pending": 0},
        "tick_count": 10,  # High tick count
    }

    prompt = build_instrument_prompt(state)

    # Should NOT include beginner guidance section
    # (though tools will still be mentioned in循环 section)
    beginner_section_count = prompt.count("核心循环工具（新手必读")
    assert beginner_section_count == 0


def test_instrument_always_includes_core_tools_in_loop_section() -> None:
    """Even without beginner guidance, loop section mentions tools."""
    from evolver.swarm import build_instrument_prompt

    state = {
        "agent_name": "test",
        "workspace_root": "/test",
        "genes": 10,
        "capsules": 5,
        "pending_solidify": False,
        "bench_pack_gate": {"armed": True},
        "supervision": {"state": "running"},
        "hitl": {"mode": "off", "pending": 0},
        "tick_count": 20,
    }

    prompt = build_instrument_prompt(state)

    # Core tools still mentioned in循环 section regardless of tick count
    assert "swarm_tick" in prompt
    assert "swarm_solidify" in prompt
    assert "循环" in prompt or "loop" in prompt.lower()


def test_beginner_guidance_mentions_soft_accept() -> None:
    """Beginner guidance mentions soft-accept for first-time setup."""
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
        "tick_count": 0,  # First tick
    }

    prompt = build_instrument_prompt(state)

    # Should mention soft-accept in beginner section
    assert "soft-accept" in prompt or "soft_accept" in prompt
    assert "no_baseline" in prompt or "pack_absent" in prompt
