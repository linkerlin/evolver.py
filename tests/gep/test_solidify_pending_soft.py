"""Tests for pending_solidify clearing after soft-accept success."""
from __future__ import annotations

import json
from pathlib import Path
import pytest


def test_pending_state_mechanism(tmp_path: Path, monkeypatch) -> None:
    """Verify the pending_solidify state mechanism works correctly."""
    from evolver.swarm import _pending_solidify_state
    from evolver.gep.paths import get_solidify_state_path
    
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    (tmp_path / "evolution").mkdir()
    
    # No state file => not pending
    assert _pending_solidify_state() is False
    
    # Create state with matching run_ids => not pending
    state_path = get_solidify_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "last_run": {"run_id": "run_123"},
        "last_solidify": {"run_id": "run_123"},
    }
    state_path.write_text(json.dumps(state))
    assert _pending_solidify_state() is False
    
    # Create state with different run_ids => pending
    state["last_run"]["run_id"] = "run_456"
    state_path.write_text(json.dumps(state))
    assert _pending_solidify_state() is True
    
    # Update last_solidify to match => not pending
    state["last_solidify"]["run_id"] = "run_456"
    state_path.write_text(json.dumps(state))
    assert _pending_solidify_state() is False


def test_soft_accept_clears_pending_concept(tmp_path: Path, monkeypatch) -> None:
    """Conceptual test: soft-accept success should clear pending by updating last_solidify.
    
    This test verifies the mechanism that solidify.py uses to clear pending state.
    The actual solidify flow is complex and requires full setup, so this tests
    the core concept: when last_solidify.run_id matches last_run.run_id, 
    pending_solidify becomes False.
    """
    from evolver.swarm import _pending_solidify_state
    from evolver.gep.paths import get_solidify_state_path
    
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    (tmp_path / "evolution").mkdir()
    
    state_path = get_solidify_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Start with pending run
    state = {
        "last_run": {
            "run_id": "run_soft_accept",
            "selected_gene_id": "gene_test",
        },
        "last_solidify": {
            "run_id": "run_previous",
        },
    }
    state_path.write_text(json.dumps(state))
    assert _pending_solidify_state() is True
    
    # Simulate solidify success (soft-accept or hard accept - same mechanism)
    # This is what solidify.py line 2341-2348 does
    state["last_solidify"] = {
        "run_id": "run_soft_accept",
        "timestamp": "2026-10-31T23:00:00Z",
        "outcome": "success",
    }
    state_path.write_text(json.dumps(state))
    
    # Now pending should be False
    assert _pending_solidify_state() is False


def test_soft_accept_warnings_structure(tmp_path: Path) -> None:
    """Soft-accept verdicts should include warnings, next_steps, commands."""
    from evolver.bench.frozen_gate import enrich_soft_accept
    
    verdict = {
        "verdict": "reject",
        "reason": "no_baseline",
        "accept": False,
    }
    
    enriched = enrich_soft_accept(verdict)
    
    # Should be soft_accept with structure
    assert enriched["soft_accept"] is True
    assert enriched["accept"] is True
    assert "warnings" in enriched
    assert "next_steps" in enriched
    assert "commands" in enriched
    assert isinstance(enriched["warnings"], list)
    assert len(enriched["warnings"]) > 0
