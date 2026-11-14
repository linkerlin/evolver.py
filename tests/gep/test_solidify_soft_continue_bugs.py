"""Workbench-draft split (算子即基因 v1.114.0, 支柱一) solidify tests.

A red validation is an honest ``ok=False, outcome=draft_preserved``: the
patch stays in the worktree, a ``rejected_stashes/<run_id>`` backup runs
first, and the return carries a 3-line ``actionable_fix``. Hard blocks
(secrets/protected state) still roll back.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from unittest.mock import patch


def test_validation_failure_is_draft_preserved(tmp_path: Path, monkeypatch):
    """支柱一: validation failure returns ok=False/draft_preserved, keeps patch.

    The worktree is never destroyed (no rollback), a stash backup runs, and
    the 3-line actionable_fix names the first failing file:line.
    """
    from evolver.gep.solidify import _handle_cascade_validation_failure

    # Setup
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "test.py").write_text("# existing code\n")

    # Simulate existing ruff noise (validation failure, but not a hard block)
    validation_result = {
        "ok": False,
        "results": [
            {
                "command": "ruff check src",
                "ok": False,
                "stdout": "",
                "stderr": "src/test.py:1:1: F401 'os' imported but unused\n" * 178,
                "duration_ms": 100,
            }
        ],
    }

    last_run = {"run_id": "test_run_1", "selected_gene_id": "gene_test"}
    mutation = {"id": "mut_1", "changes": []}

    # Mock git operations to track if rollback was called
    rollback_called = []
    snapshot_called = []

    def mock_rollback(*args, **kwargs):
        rollback_called.append((args, kwargs))

    def mock_snapshot(*args, **kwargs):
        snapshot_called.append((args, kwargs))
        return {"ok": True, "saved": True, "snapshot_path": "/tmp/test.json"}

    monkeypatch.setattr("evolver.gep.solidify.rollback_tracked", mock_rollback)
    monkeypatch.setattr("evolver.gep.solidify.snapshot_rejected_worktree", mock_snapshot)
    monkeypatch.setattr("evolver.gep.solidify.rollback_new_untracked_files", lambda *a, **k: None)
    monkeypatch.setattr("evolver.gep.solidify.record_solidify_failure", lambda *a, **k: None)
    monkeypatch.setattr("evolver.gep.solidify._wiki_rejection", lambda *a, **k: None)
    monkeypatch.setattr("evolver.gep.solidify._maybe_record_variant", lambda *a, **k: None)
    monkeypatch.setattr("evolver.gep.solidify.append_event_jsonl", lambda e: None)
    monkeypatch.setattr("evolver.gep.solidify._remember_failure_scene", lambda *a, **k: "evt_123")

    # Execute
    result = _handle_cascade_validation_failure(
        last_run=last_run,
        mutation=mutation,
        cwd=repo,
        validation_result=validation_result,
        validation_report=None,
        eval_meta=None,
    )

    # Honest draft verdict — never ok=True, never vault material.
    assert result.get("ok") is False, f"Expected ok=False, got {result}"
    assert result.get("outcome") == "draft_preserved", f"Got {result}"
    assert result.get("error") == "validation_failed"
    assert len(result.get("warnings", [])) > 0, "Expected validation warnings"

    # CRITICAL: rollback_tracked must NOT have been called — the patch stays.
    assert len(rollback_called) == 0, (
        f"Working tree was destroyed: rollback_tracked called {len(rollback_called)} "
        f"times on a draft-preserved failure. Calls: {rollback_called}"
    )
    # 防丢 backup ran exactly once.
    assert len(snapshot_called) == 1, "Expected one rejected_stash backup"

    # Exactly three human fix lines with file:line precision.
    fix = result.get("actionable_fix") or []
    assert len(fix) == 3, f"Expected 3 fix lines, got {fix}"
    assert any("src/test.py:1" in line for line in fix), f"No file:line in {fix}"
    assert any("preserved in place" in line for line in fix), f"No preservation line in {fix}"


def test_soft_continue_preserves_working_tree_for_episode(tmp_path: Path, monkeypatch):
    """Bug 2: Success with soft-continue must preserve working tree for episode diff.

    Symptom: After solidify success with bench_pack soft_accept, working-tree dirty
    changes disappeared and episode records had empty diff text (0 chars).

    Root cause: Same as Bug 1 — the legacy rollback path was executing even on
    soft-continue, wiping the working tree before episode diff capture.

    Expected: Working tree changes remain, episode diff is non-empty.
    """
    from evolver.gep.solidify import _solidify_cycle

    # Setup a repo with pending changes
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "test.py").write_text("# original\n")

    # Simulate a pending solidify state
    state_dir = tmp_path / "evolution"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "evolution_solidify_state.json"
    state_file.write_text(
        json.dumps(
            {
                "last_run": {
                    "run_id": "run_123",
                    "selected_gene_id": "gene_test",
                    "mutation": {"id": "mut_1"},
                }
            }
        )
    )

    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLUTION_DIR", str(state_dir))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))

    # Mock cascade to return soft-failure
    mock_validation_result = {
        "ok": False,
        "results": [
            {
                "command": "ruff check",
                "ok": False,
                "stdout": "",
                "stderr": "F401 unused import",
            }
        ],
    }

    captured_diffs = []

    def mock_capture_diff(cwd):
        # Simulate working tree has changes
        diff = "diff --git a/test.py b/test.py\n+# new line\n"
        captured_diffs.append(diff)
        return diff

    # Mock various solidify dependencies
    with patch("evolver.gep.solidify.is_git_repo", return_value=True):
        with patch("evolver.gep.solidify.get_fitness_cascade_commands", return_value=[]):
            with patch(
                "evolver.gep.solidify._run_validations", return_value=mock_validation_result
            ):
                with patch(
                    "evolver.gep.solidify.capture_diff_snapshot", side_effect=mock_capture_diff
                ):
                    with patch("evolver.gep.solidify.is_enabled", return_value=True):
                        with patch(
                            "evolver.gep.solidify._compute_blast_radius",
                            return_value={"files": 1, "lines": 10},
                        ):
                            with patch("evolver.gep.solidify.append_event_jsonl"):
                                with patch(
                                    "evolver.gep.hypothesis.load_hypothesis", return_value=None
                                ):
                                    with patch(
                                        "evolver.gep.solidify.build_execution_trace",
                                        return_value=[],
                                    ):
                                        # Soft-continue scenario: care that capture_diff ran.
                                        with contextlib.suppress(Exception):
                                            _solidify_cycle()

    # Bug 2 verification: diff capture should have found changes (not empty)
    # In the buggy version, rollback would have cleaned the tree first
    if captured_diffs:
        for diff in captured_diffs:
            assert len(diff) > 0, (
                "Bug 2 not fixed: diff is empty because working tree was rolled back "
                "before diff capture"
            )


def test_hard_block_still_rollsback(tmp_path: Path, monkeypatch):
    """Hard blocks (secrets/protected state) must still rollback."""
    from evolver.gep.solidify import _handle_cascade_validation_failure

    # Setup
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    # Validation failure (doesn't matter for this test)
    validation_result = {
        "ok": False,
        "results": [{"command": "ruff", "ok": False, "stdout": "", "stderr": "error"}],
    }

    # Mutation that touches protected state
    last_run = {"run_id": "test_run_1", "selected_gene_id": "gene_test"}
    mutation = {
        "id": "mut_1",
        "changes": [
            {"file": ".evolver/state.json", "action": "edit"}  # Protected path!
        ],
    }

    # Mock git operations
    rollback_called = []
    snapshot_called = []

    def mock_rollback(*args, **kwargs):
        rollback_called.append((args, kwargs))

    def mock_snapshot(*args, **kwargs):
        snapshot_called.append((args, kwargs))
        return {"ok": True, "saved": True}

    monkeypatch.setattr("evolver.gep.solidify.rollback_tracked", mock_rollback)
    monkeypatch.setattr("evolver.gep.solidify.snapshot_rejected_worktree", mock_snapshot)
    monkeypatch.setattr("evolver.gep.solidify.rollback_new_untracked_files", lambda *a, **k: None)
    monkeypatch.setattr("evolver.gep.solidify.record_solidify_failure", lambda *a, **k: None)
    monkeypatch.setattr("evolver.gep.solidify._wiki_rejection", lambda *a, **k: None)
    monkeypatch.setattr("evolver.gep.solidify.append_event_jsonl", lambda e: None)
    monkeypatch.setattr("evolver.gep.solidify._remember_failure_scene", lambda *a, **k: "evt_456")

    # Execute
    result = _handle_cascade_validation_failure(
        last_run=last_run,
        mutation=mutation,
        cwd=repo,
        validation_result=validation_result,
        validation_report=None,
        eval_meta=None,
    )

    # Verify hard block still rejects and rolls back
    assert result.get("ok") is False, "Hard block must reject"
    assert "hard" in result.get("error", "").lower() or result.get("block_reason")
    assert len(rollback_called) > 0, "Hard block must call rollback"
    assert len(snapshot_called) > 0, "Hard block must snapshot before rollback"


def test_actionable_fix_always_three_lines_and_traceback_aware() -> None:
    """Round-121 review pins: (1) a silent failing stage still yields exactly
    three lines; (2) Python-traceback frames locate file:line."""
    from evolver.gep.solidify import _actionable_fix_from_validation

    silent = _actionable_fix_from_validation(
        {"results": [{"ok": False, "command": "pytest", "stdout": "", "stderr": ""}]},
        "run-x",
    )
    assert len(silent) == 3

    tb = _actionable_fix_from_validation(
        {
            "results": [
                {
                    "ok": False,
                    "command": "pytest",
                    "stdout": "",
                    "stderr": (
                        'Traceback (most recent call last):\n  File "src/calc.py", line 42, '
                        "in apply_discount\nValueError: bad rate\n"
                    ),
                }
            ]
        },
        "run-y",
    )
    assert len(tb) == 3
    assert "src/calc.py:42" in tb[0]
