"""Tests for evolver.gep.paths — equivalent to evolver/test/paths.test.js."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep import paths


def test_get_workspace_root_prefers_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    assert paths.get_workspace_root() == tmp_path


def test_get_workspace_root_falls_back_to_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENCLAW_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    assert paths.get_workspace_root() == tmp_path


def test_get_evolution_dir_honors_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ed = tmp_path / "custom_evolution"
    monkeypatch.setenv("EVOLUTION_DIR", str(ed))
    assert paths.get_evolution_dir() == ed


def test_get_gep_assets_dir_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    assert paths.get_gep_assets_dir() == tmp_path / ".evolver" / "gep"


def test_get_repo_root_discovers_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EVOLVER_QUIET_PARENT_GIT", "1")
    assert paths.get_repo_root() == tmp_path


def test_workspace_id_is_stable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    first = paths.get_workspace_id()
    second = paths.get_workspace_id()
    assert first == second
    assert len(first) == 32
