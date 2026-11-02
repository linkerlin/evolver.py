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


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def test_capture_diff_snapshot_includes_untracked_new_file(tmp_path: Path) -> None:
    """DEBUG #57: a new file that was never git-added is part of the scene."""
    _init_repo(tmp_path)
    (tmp_path / "notes.md").write_text("untracked-notes-marker\n", encoding="utf-8")
    snap = capture_diff_snapshot(tmp_path)
    assert "diff --git a/notes.md b/notes.md" in snap
    assert "+untracked-notes-marker" in snap


def test_capture_diff_snapshot_includes_staged_new_file(tmp_path: Path) -> None:
    """A new file already in the index stays visible via git diff HEAD."""
    _init_repo(tmp_path)
    (tmp_path / "added.py").write_text("staged-new-marker\n", encoding="utf-8")
    subprocess.run(["git", "add", "added.py"], cwd=tmp_path, check=True, capture_output=True)
    snap = capture_diff_snapshot(tmp_path)
    assert "staged-new-marker" in snap


def test_capture_diff_snapshot_keeps_tracked_edit_beside_untracked(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("tracked-edit-marker\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("untracked-notes-marker\n", encoding="utf-8")
    snap = capture_diff_snapshot(tmp_path)
    assert "tracked-edit-marker" in snap
    assert "untracked-notes-marker" in snap


def test_capture_diff_snapshot_skips_noise_and_binaries(tmp_path: Path) -> None:
    """Explosion-radius noise and binaries must not crowd the mutation scene."""
    _init_repo(tmp_path)
    (tmp_path / "notes.md").write_text("untracked-notes-marker\n", encoding="utf-8")
    noise = {
        tmp_path / ".venv" / "lib" / "x.py": "noise-venv-marker\n",
        tmp_path / "pkg" / "node_modules" / "leftpad.js": "noise-node-modules-marker\n",
        tmp_path / "src" / "__pycache__" / "x.pyc": "noise-pycache-marker\n",
        tmp_path / "memory" / "evolution_solidify_state.json": "noise-memory-marker\n",
        tmp_path / ".evolver" / "gep" / "events.jsonl": "noise-evolver-marker\n",
        tmp_path / ".env": "API_KEY=noise-env-marker\n",
    }
    for path, text in noise.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    blob = tmp_path / "payload.bin"
    blob.write_bytes(b"\x00noise-binary-marker")
    snap = capture_diff_snapshot(tmp_path)
    assert "untracked-notes-marker" in snap
    for marker in (
        "noise-venv-marker",
        "noise-node-modules-marker",
        "noise-pycache-marker",
        "noise-memory-marker",
        "noise-evolver-marker",
        "noise-env-marker",
        "noise-binary-marker",
    ):
        assert marker not in snap


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
