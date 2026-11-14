"""Tests for status & FSM phase mapping across IDLE and ACTIVE_RUN."""

from __future__ import annotations

import json
from pathlib import Path


def test_status_idle_after_settled(tmp_path: Path, monkeypatch) -> None:
    """Status shows pending_solidify=False and fsm_state='IDLE' when settled."""
    from evolver.gep.paths import get_solidify_state_path
    from evolver.swarm import evolve_status, swarm_status

    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    (tmp_path / "evolution").mkdir(parents=True)

    state_path = get_solidify_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "last_run": {"run_id": "run_completed"},
        "last_solidify": {"run_id": "run_completed", "outcome": "success"},
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")

    status = swarm_status()
    assert status["ok"] is True
    assert status["pending_solidify"] is False
    assert status["fsm_state"] == "IDLE"

    ev = evolve_status()
    assert ev["ok"] is True
    assert ev["fsm_state"] == "IDLE"
    assert ev["next_action"] == "evolve_begin"


def test_status_active_run_before_settle(tmp_path: Path, monkeypatch) -> None:
    """Status shows pending_solidify=True and fsm_state='ACTIVE_RUN' when run is open."""
    from evolver.gep.paths import get_solidify_state_path
    from evolver.swarm import evolve_status, swarm_status

    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    (tmp_path / "evolution").mkdir(parents=True)

    state_path = get_solidify_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "last_run": {"run_id": "run_new"},
        "last_solidify": {"run_id": "run_old"},
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")

    status = swarm_status()
    assert status["ok"] is True
    assert status["pending_solidify"] is True
    assert status["fsm_state"] == "ACTIVE_RUN"

    ev = evolve_status()
    assert ev["fsm_state"] == "ACTIVE_RUN"
    assert ev["next_action"] == "evolve_settle"


def test_evolve_status_core_fields(tmp_path: Path, monkeypatch) -> None:
    """evolve_status exposes zero-jargon health fields alongside FSM metadata."""
    from evolver.swarm import evolve_status

    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    (tmp_path / "evolution").mkdir(parents=True)

    st = evolve_status()
    assert st["ok"] is True
    for key in (
        "version",
        "fsm_state",
        "allowed_tools",
        "vault_operators",
        "vault_capsules",
        "workbench_drafts",
        "available_lenses",
    ):
        assert key in st
