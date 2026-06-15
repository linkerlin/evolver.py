"""Tests for evolver.adapters.scripts.runtime_paths.

Covers the contracts ported from evolver/src/adapters/scripts/_runtimePaths.js:
  - resolve_project_dir: host env → cwd fallback
  - _fs_workspace_root: OPENCLAW_WORKSPACE → git root → project dir
  - _fs_workspace_id: atomic create, symlink rejection, EEXIST race
  - resolve_workspace_id: env override → paths → FS fallback
  - find_memory_graph: env → evolver root → user fallback
  - is_git_workspace: true in repo, false outside

Equivalent to test/resolveProjectDir.test.js, test/resolveWorkspaceId.test.js.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from evolver.adapters.scripts import runtime_paths

# ---------------------------------------------------------------------------
# resolve_project_dir
# ---------------------------------------------------------------------------


class TestResolveProjectDir:
    def test_cursor_project_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CURSOR_PROJECT_DIR", str(tmp_path))
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        assert runtime_paths.resolve_project_dir() == tmp_path

    def test_claude_project_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("CURSOR_PROJECT_DIR", raising=False)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        assert runtime_paths.resolve_project_dir() == tmp_path

    def test_cursor_takes_precedence(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        other = tmp_path / "other"
        other.mkdir()
        monkeypatch.setenv("CURSOR_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(other))
        assert runtime_paths.resolve_project_dir() == tmp_path

    def test_falls_back_to_cwd(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("CURSOR_PROJECT_DIR", raising=False)
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        assert runtime_paths.resolve_project_dir() == tmp_path

    def test_stale_env_ignored(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CURSOR_PROJECT_DIR", str(tmp_path / "nonexistent"))
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        assert runtime_paths.resolve_project_dir() == tmp_path

    def test_empty_env_ignored(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CURSOR_PROJECT_DIR", "   ")
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        assert runtime_paths.resolve_project_dir() == tmp_path


# ---------------------------------------------------------------------------
# _fs_workspace_root
# ---------------------------------------------------------------------------


class TestFsWorkspaceRoot:
    def test_openclaw_workspace_override(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ws = tmp_path / "custom-ws"
        ws.mkdir()
        monkeypatch.setenv("OPENCLAW_WORKSPACE", str(ws))
        assert runtime_paths._fs_workspace_root(tmp_path) == ws

    def test_git_repo_root(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        sub = tmp_path / "subdir"
        sub.mkdir()
        assert runtime_paths._fs_workspace_root(sub).resolve() == tmp_path.resolve()

    def test_workspace_subdir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        (tmp_path / "workspace").mkdir()
        result = runtime_paths._fs_workspace_root(tmp_path)
        assert result.name == "workspace"

    def test_no_git_returns_project_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
        result = runtime_paths._fs_workspace_root(tmp_path)
        assert result == tmp_path


# ---------------------------------------------------------------------------
# _fs_workspace_id
# ---------------------------------------------------------------------------


class TestFsWorkspaceId:
    def test_creates_and_returns_id(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
        monkeypatch.delenv("EVOLVER_WORKSPACE_ID", raising=False)
        # No git → project dir itself.
        result = runtime_paths._fs_workspace_id(tmp_path)
        assert result is not None
        assert len(result) == 32
        id_file = tmp_path / ".evolver" / "workspace-id"
        assert id_file.exists()
        assert id_file.read_text(encoding="utf-8").strip() == result

    def test_id_stable_across_calls(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
        monkeypatch.delenv("EVOLVER_WORKSPACE_ID", raising=False)
        first = runtime_paths._fs_workspace_id(tmp_path)
        second = runtime_paths._fs_workspace_id(tmp_path)
        assert first == second

    def test_rejects_symlinked_evolver_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
        target = tmp_path / "target"
        target.mkdir()
        link = tmp_path / ".evolver"
        try:
            link.symlink_to(target)
        except OSError:
            pytest.skip("symlinks not supported on this platform")
        result = runtime_paths._fs_workspace_id(tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# resolve_workspace_id
# ---------------------------------------------------------------------------


class TestResolveWorkspaceId:
    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_WORKSPACE_ID", "my-custom-id")
        assert runtime_paths.resolve_workspace_id() == "my-custom-id"

    def test_fs_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.delenv("EVOLVER_WORKSPACE_ID", raising=False)
        # Pass evolver_root=None to force FS fallback.
        result = runtime_paths.resolve_workspace_id(None, tmp_path)
        assert result is not None
        assert len(result) == 32


# ---------------------------------------------------------------------------
# find_memory_graph
# ---------------------------------------------------------------------------


class TestFindMemoryGraph:
    def test_env_override(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        custom = tmp_path / "custom.jsonl"
        monkeypatch.setenv("MEMORY_GRAPH_PATH", str(custom))
        assert runtime_paths.find_memory_graph(None) == custom

    def test_user_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("MEMORY_GRAPH_PATH", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # Force evolver_root=None so the user fallback path is taken.
        monkeypatch.setattr(
            runtime_paths, "find_evolver_root", lambda: None
        )
        result = runtime_paths.find_memory_graph(None)
        assert result == tmp_path / ".evolver" / "memory" / "evolution" / "memory_graph.jsonl"
        assert result.parent.exists()


# ---------------------------------------------------------------------------
# is_git_workspace
# ---------------------------------------------------------------------------


class TestIsGitWorkspace:
    def test_true_in_repo(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        assert runtime_paths.is_git_workspace(tmp_path) is True

    def test_false_outside_repo(self, tmp_path: Path) -> None:
        assert runtime_paths.is_git_workspace(tmp_path) is False

    def test_never_raises(self, tmp_path: Path) -> None:
        # Non-existent path.
        result = runtime_paths.is_git_workspace(tmp_path / "nope")
        assert result is False


# ---------------------------------------------------------------------------
# find_evolver_root
# ---------------------------------------------------------------------------


class TestFindEvolverRoot:
    def test_env_override_invalid_falls_through(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("EVOLVER_ROOT", str(tmp_path / "nonexistent"))
        # Invalid env root falls through to dev layout, which finds the repo.
        root = runtime_paths.find_evolver_root()
        assert root is not None
        assert (root / "src" / "evolver" / "__init__.py").exists()

    def test_dev_layout_detected(self) -> None:
        # This file is in the repo — find_evolver_root should find it.
        root = runtime_paths.find_evolver_root()
        assert root is not None
        assert (root / "src" / "evolver" / "__init__.py").exists()
