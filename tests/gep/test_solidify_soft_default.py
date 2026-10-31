"""Tests for soft-default validation policy in solidify.

Covers beginner-soft-default design (2026-10-31): validation failures now
soft-continue with warnings, still write experience, no worktree rollback
for soft failures. Only hard-block secrets and protected state paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from evolver.gep import solidify
from evolver.gep.paths import get_workspace_root


class TestSoftValidationFailure:
    """Test that validation failures soft-continue instead of hard-rejecting."""

    def test_validation_failure_returns_ok_true_with_warnings(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Validation failure → ok=True, severity=soft, warnings populated."""
        # Setup workspace with pending run
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(workspace))
        
        # Mock git repo
        (workspace / ".git").mkdir()
        
        # Create minimal gene and pending run
        from evolver.gep.paths import get_solidify_state_path
        
        state_path = get_solidify_state_path()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        
        pending_run = {
            "run_id": "test_run_001",
            "timestamp": "2026-10-31T00:00:00.000Z",
            "mutation": {
                "gene_id": "gene_test",
                "changes": [{"file": "test.py", "content": "print('hello')"}],
            },
            "selected_gene_id": "gene_test",
        }
        
        state_path.write_text(
            json.dumps({"last_run": pending_run}, indent=2), encoding="utf-8"
        )
        
        # Mock failed validation
        def fake_run_validations(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return {
                "ok": False,
                "results": [
                    {"ok": False, "command": "ruff check", "stdout": "", "stderr": "errors found"}
                ],
                "started_at": 0,
                "finished_at": 100,
                "duration_ms": 100,
            }
        
        monkeypatch.setattr(solidify, "_run_validations", fake_run_validations)
        
        # Mock other dependencies
        monkeypatch.setattr(solidify, "is_git_repo", lambda _: True)
        monkeypatch.setattr(solidify, "touches_verifier_surface", lambda *args: False)
        monkeypatch.setattr(solidify, "run_anchor_suite", lambda *args: None)
        
        # Enable soft-default
        from evolver.gep.feature_flags import is_enabled
        original_is_enabled = is_enabled
        
        def mock_is_enabled(flag: str) -> bool:
            if flag == "enable_fitness_cascade":
                return True
            return original_is_enabled(flag)
        
        monkeypatch.setattr("evolver.gep.solidify.is_enabled", mock_is_enabled)
        
        # TODO: Complete test implementation
        # This is a skeleton showing the pattern for Task 2
        pytest.skip("Implementation in progress for Task 2")

    def test_empty_cascade_still_writes_experience(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Empty cascade (all skipped) → ok=True with warnings, experience written."""
        # Similar pattern to above
        pytest.skip("Implementation in progress for Task 2")

    def test_hard_block_secrets_still_fails(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Mutation touching secrets → ok=False, rollback happens."""
        pytest.skip("Implementation in progress for Task 2")

    def test_hard_block_protected_state_still_fails(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Mutation touching ~/.evolver → ok=False, rollback happens."""
        pytest.skip("Implementation in progress for Task 2")


class TestNoWorktreeRollbackOnSoft:
    """Test that soft validation failures don't rollback the worktree."""

    def test_soft_validation_preserves_worktree_changes(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Soft validation failure leaves worktree files unchanged."""
        pytest.skip("Implementation in progress for Task 2")

    def test_hard_block_still_rolls_back(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Hard block (secrets/protected) still triggers rollback."""
        pytest.skip("Implementation in progress for Task 2")


class TestExperienceWrittenOnSoft:
    """Test that experience (Gene/Episode/events) is written even on soft failures."""

    def test_soft_validation_writes_gene(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Soft validation failure still persists Gene to state_root."""
        pytest.skip("Implementation in progress for Task 2")

    def test_soft_validation_writes_episode(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Soft validation failure records episode in evolution/episodes/."""
        pytest.skip("Implementation in progress for Task 2")

    def test_soft_validation_writes_event(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Soft validation failure appends event to events.jsonl."""
        pytest.skip("Implementation in progress for Task 2")
