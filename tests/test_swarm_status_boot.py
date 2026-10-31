"""Tests for status/boot dual-path copy reflecting soft-accept state."""
from __future__ import annotations

import json
from pathlib import Path
import pytest


def test_status_pending_false_after_cleared(tmp_path: Path, monkeypatch) -> None:
    """Status shows pending_solidify=False when last_solidify matches last_run."""
    from evolver.swarm import swarm_status
    from evolver.gep.paths import get_solidify_state_path
    
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    (tmp_path / "evolution").mkdir(parents=True)
    
    # Setup state with matching run_ids (pending cleared)
    state_path = get_solidify_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "last_run": {"run_id": "run_completed"},
        "last_solidify": {"run_id": "run_completed", "outcome": "success"},
    }
    state_path.write_text(json.dumps(state))
    
    status = swarm_status()
    assert status["ok"] is True
    assert status["pending_solidify"] is False


def test_status_pending_true_before_solidify(tmp_path: Path, monkeypatch) -> None:
    """Status shows pending_solidify=True when run is unsaved."""
    from evolver.swarm import swarm_status
    from evolver.gep.paths import get_solidify_state_path
    
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    (tmp_path / "evolution").mkdir(parents=True)
    
    # Setup state with different run_ids (pending)
    state_path = get_solidify_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "last_run": {"run_id": "run_new"},
        "last_solidify": {"run_id": "run_old"},
    }
    state_path.write_text(json.dumps(state))
    
    status = swarm_status()
    assert status["ok"] is True
    assert status["pending_solidify"] is True


def test_boot_reflects_pending_state(tmp_path: Path, monkeypatch) -> None:
    """Boot includes state with correct pending_solidify value."""
    from evolver.swarm import swarm_boot
    from evolver.gep.paths import get_solidify_state_path
    
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    (tmp_path / "evolution").mkdir(parents=True)
    
    # No pending state
    state_path = get_solidify_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    if state_path.exists():
        state_path.unlink()
    
    boot = swarm_boot(agent_name="test")
    assert boot["ok"] is True
    assert "state" in boot
    assert boot["state"]["pending_solidify"] is False


def test_status_includes_soft_warnings_concept(tmp_path: Path, monkeypatch) -> None:
    """Status could include last soft-accept warnings (conceptual).
    
    This is a forward-looking test. The current implementation doesn't 
    explicitly track last_soft_accept warnings in status, but the mechanism
    is in place via events.jsonl. If needed, status could read the last
    event and include soft_warnings.
    """
    from evolver.swarm import swarm_status
    
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    (tmp_path / "evolution").mkdir(parents=True)
    
    status = swarm_status()
    assert status["ok"] is True
    # Status always has these core fields
    assert "version" in status
    assert "pending_solidify" in status
    assert "genes" in status
    assert "capsules" in status
