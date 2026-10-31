"""Test that instrument prompt aligns with USABILITY_SOFT_REASONS for drop/flat/regression."""

from __future__ import annotations

import re

from evolver.swarm import build_instrument_prompt


def test_instrument_does_not_hard_reject_drop_flat_regression():
    """Instrument must not claim drop/flat/regression are hard rejects.
    
    Soft-default policy treats drop/flat/regression as soft-accept with warnings.
    Hard blocks only: secrets/credentials, ~/.evolver/engine-protected paths, val_seal.
    """
    text = build_instrument_prompt({
        "agent_name": "test-agent",
        "workspace_root": "/test",
        "genes": 0,
        "capsules": 0,
        "pending_solidify": False,
        "bench_pack_gate": {"armed": False},
        "train_ids": [],
        "supervision": {"state": "running"},
        "hitl": {"mode": "off", "pending": 0},
        "tick_count": 0,
    })
    
    # Must not say "drop/flat/regression ... 仍硬拒绝"
    assert not re.search(r"drop\s*/\s*flat\s*/\s*regression[^\n]*仍硬拒绝", text), \
        "Instrument must not claim drop/flat/regression are still hard-rejected"
    
    # Hard blocks should only be secrets / protected paths / val_seal
    # The instrument should mention these as the actual hard gates
    assert "val_seal" in text or "密封" in text, \
        "Instrument should mention val_seal as a hard gate"
    assert "secrets" in text.lower() or "密钥" in text or "credentials" in text.lower(), \
        "Instrument should mention secrets/credentials as a hard gate"
    assert "~/.evolver" in text or ".evolver" in text, \
        "Instrument should mention protected engine paths"


def test_instrument_mentions_soft_continue_for_usability_gaps():
    """Instrument should explain soft-continue for usability gaps."""
    text = build_instrument_prompt({
        "agent_name": "test-agent",
        "workspace_root": "/test",
        "genes": 0,
        "capsules": 0,
        "pending_solidify": False,
        "bench_pack_gate": {"armed": False},
        "train_ids": [],
        "supervision": {"state": "running"},
        "hitl": {"mode": "off", "pending": 0},
        "tick_count": 0,
    })
    
    # Should mention soft-continue / soft-accept for usability gaps
    assert "soft" in text.lower(), \
        "Instrument should mention soft-continue or soft-accept"
    assert "pack_absent" in text or "no_baseline" in text or "unmeasured" in text, \
        "Instrument should mention specific soft-accept conditions"
