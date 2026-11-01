"""Tests for migrate-state checklist integration."""

from __future__ import annotations

from pathlib import Path


def test_migration_checklist_no_legacy(tmp_path: Path, monkeypatch) -> None:
    """No migration checklist item when no legacy state exists."""
    from evolver.ops.migrate_state import migration_checklist

    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))

    # Clean workspace with no legacy paths
    result = migration_checklist(tmp_path)

    assert result["needed"] is False
    assert "step" not in result


def test_migration_checklist_with_legacy_evolution(tmp_path: Path, monkeypatch) -> None:
    """Migration checklist item appears when legacy evolution exists."""
    from evolver.ops.migrate_state import migration_checklist

    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))

    # Create legacy evolution path with data
    legacy_evo = tmp_path / "memory" / "evolution"
    legacy_evo.mkdir(parents=True)
    (legacy_evo / "events.jsonl").write_text('{"type":"test"}\n')

    result = migration_checklist(tmp_path)

    assert result["needed"] is True
    assert "step" in result
    step = result["step"]
    assert step["name"] == "migrate_legacy_state"
    assert step["status"] == "recommended"
    assert "command" in step
    assert "evolver migrate-state" in step["command"]


def test_migration_checklist_with_legacy_gep(tmp_path: Path, monkeypatch) -> None:
    """Migration checklist item appears when legacy .evolver/gep exists."""
    from evolver.ops.migrate_state import migration_checklist

    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))

    # Create legacy GEP path with data
    legacy_gep = tmp_path / ".evolver" / "gep"
    legacy_gep.mkdir(parents=True)
    (legacy_gep / "genes.json").write_text("[]")

    result = migration_checklist(tmp_path)

    assert result["needed"] is True
    assert result["step"]["name"] == "migrate_legacy_state"


def test_migration_checklist_empty_legacy_dirs_ignored(tmp_path: Path, monkeypatch) -> None:
    """Empty legacy directories don't trigger migration checklist."""
    from evolver.ops.migrate_state import migration_checklist

    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))

    # Create empty legacy directories
    (tmp_path / "memory" / "evolution").mkdir(parents=True)
    (tmp_path / ".evolver" / "gep").mkdir(parents=True)

    # Empty dirs => no migration needed
    result = migration_checklist(tmp_path)

    assert result["needed"] is False


def test_migration_checklist_integration_concept(tmp_path: Path, monkeypatch) -> None:
    """Conceptual test: migration_checklist can be called from swarm boot/status.

    This test verifies the mechanism exists and works. Full integration into
    swarm_boot/swarm_status would add the checklist to their return payloads
    when legacy state is detected.
    """
    from evolver.ops.migrate_state import migration_checklist
    from evolver.swarm import swarm_status

    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))

    # Create legacy state
    legacy_evo = tmp_path / "memory" / "evolution"
    legacy_evo.mkdir(parents=True)
    (legacy_evo / "events.jsonl").write_text('{"type":"test"}\n')

    # Verify migration_checklist works
    migrate_check = migration_checklist(tmp_path)
    assert migrate_check["needed"] is True

    # Verify status can be called (doesn't need to include migrate check yet)
    status = swarm_status()
    assert status["ok"] is True

    # In a full implementation, status would include:
    # if migrate_check["needed"]:
    #     status["migration_needed"] = migrate_check["step"]
