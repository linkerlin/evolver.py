"""Pure-function tests for evolver.gep.git_ops (solidify-helpers subset)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from evolver.gep.git_ops import (
    capture_diff_snapshot,
    count_file_lines,
    is_constraint_counted_path,
    is_critical_protected_path,
    is_git_repo,
    normalize_rel_path,
    rollback_new_untracked_files,
    rollback_tracked,
    try_run_cmd,
)


def test_normalize_strips_backslashes_and_dot_slash() -> None:
    assert normalize_rel_path(".\\src\\evolve.js") == "src/evolve.js"
    assert normalize_rel_path("./src/evolve.js") == "src/evolve.js"
    assert normalize_rel_path("src/gep/solidify.py") == "src/gep/solidify.py"


def test_normalize_repeated_dot_slash() -> None:
    assert normalize_rel_path("././src/x.py") == "src/x.py"


def test_normalize_empty_and_whitespace() -> None:
    assert normalize_rel_path("") == ""
    assert normalize_rel_path("  ") == ""


def test_protects_env_and_git() -> None:
    assert is_critical_protected_path(".env") is True
    assert is_critical_protected_path(".git/config") is True


def test_protects_lockfiles_and_manifests() -> None:
    assert is_critical_protected_path("package.json") is True
    assert is_critical_protected_path("pyproject.toml") is True
    assert is_critical_protected_path("uv.lock") is True


def test_allows_normal_source_paths() -> None:
    assert is_critical_protected_path("src/evolve.py") is False
    assert is_critical_protected_path("tests/test_git_ops.py") is False


def test_critical_uses_normalized_path() -> None:
    assert is_critical_protected_path(".\\package.json") is True
    assert is_critical_protected_path("./.env") is True


def test_counts_source_files() -> None:
    assert is_constraint_counted_path("src/evolve.py") is True
    assert is_constraint_counted_path("scripts/foo.py") is True


def test_excludes_venv_and_caches() -> None:
    assert is_constraint_counted_path("node_modules/dotenv/index.js") is False
    assert is_constraint_counted_path(".venv/lib/x.py") is False
    assert is_constraint_counted_path("__pycache__/x.pyc") is False
    assert is_constraint_counted_path(".git/config") is False


def test_constraint_excludes_critical_protected() -> None:
    assert is_constraint_counted_path(".env") is False
    assert is_constraint_counted_path("pyproject.toml") is False


def test_count_file_lines(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("a\nb\nc\n", encoding="utf-8")
    assert count_file_lines(p) == 3
    assert count_file_lines(tmp_path / "missing.txt") == 0


def test_try_run_cmd_default_on_failure(tmp_path: Path) -> None:
    out = try_run_cmd(["rev-parse", "--git-dir"], cwd=tmp_path, default="NOT_A_REPO")
    assert out == "NOT_A_REPO"


def test_is_git_repo_true_and_false(tmp_path: Path) -> None:
    assert is_git_repo(tmp_path) is False
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    assert is_git_repo(tmp_path) is True


def test_capture_diff_snapshot_truncates(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=tmp_path, check=True, capture_output=True
    )
    (tmp_path / "f.txt").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "i"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "f.txt").write_text("x" * 200 + "\n", encoding="utf-8")
    snap = capture_diff_snapshot(tmp_path, max_chars=50)
    assert len(snap) <= 80
    assert "[truncated]" in snap or len(snap) <= 50


def test_rollback_mode_none(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    result = rollback_tracked(mode="none", cwd=tmp_path)
    assert result["ok"] is True
    assert result["mode"] == "none"


def test_rollback_unknown_mode(tmp_path: Path) -> None:
    result = rollback_tracked(mode="explode", cwd=tmp_path)
    assert result["ok"] is False
    assert "Unknown" in str(result["error"])


def test_rollback_new_untracked_files(tmp_path: Path) -> None:
    f = tmp_path / "new.py"
    f.write_text("x\n", encoding="utf-8")
    rollback_new_untracked_files(["new.py"], cwd=tmp_path)
    assert not f.exists()


def test_rollback_new_untracked_missing_is_safe(tmp_path: Path) -> None:
    rollback_new_untracked_files(["does-not-exist.py"], cwd=tmp_path)
