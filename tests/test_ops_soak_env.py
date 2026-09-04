"""Soak environment helper (演进方案.md §10) — keep runtime off the git tree."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.ops.soak_env import (
    evolution_dir_inside_repo,
    exports_shell,
    path_is_inside,
    setup,
    soak_root,
    status,
)


def test_path_is_inside(tmp_path: Path) -> None:
    inner = tmp_path / "a" / "b"
    inner.mkdir(parents=True)
    assert path_is_inside(inner, tmp_path) is True
    assert path_is_inside(tmp_path, inner) is False


def test_setup_is_idempotent(temp_workspace: Path) -> None:
    lessons = temp_workspace / "memory" / "evolution" / "LESSONS_LEARNED.md"
    lessons.parent.mkdir(parents=True, exist_ok=True)
    lessons.write_text("# lessons\n", encoding="utf-8")

    first = setup()
    assert first["ok"] is True
    assert Path(first["evolution_dir"]).is_dir()
    assert Path(first["gep_assets_dir"]).is_dir()
    assert Path(first["env_sh"]).is_file()
    assert first["copied_lessons"] is True
    assert (Path(first["evolution_dir"]) / "LESSONS_LEARNED.md").is_file()

    second = setup()
    assert second["copied_lessons"] is False
    assert soak_root() == Path(first["root"])


def test_exports_point_at_soak_root(temp_workspace: Path) -> None:
    text = exports_shell()
    root = soak_root()
    assert f'EVOLUTION_DIR="{root / "evolution"}"' in text
    assert f'GEP_ASSETS_DIR="{root / "gep"}"' in text


def test_status_flags_in_repo_layout(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # temp_workspace sets EVOLUTION_DIR under the sandbox, not the product repo.
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    monkeypatch.setenv("EVOLUTION_DIR", str(temp_workspace / "memory" / "evolution"))
    assert evolution_dir_inside_repo() is True
    report = status()
    assert report["inside_repo"] is True
    assert report["metrics"]["gated_runs"] >= 0


def test_cli_soak_setup_and_exports(
    temp_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from evolver.cli import main

    assert main(["soak", "setup"]) == 0
    out = capsys.readouterr().out
    assert "env.sh" in out
    assert main(["soak", "exports"]) == 0
    exports = capsys.readouterr().out
    assert "export EVOLUTION_DIR=" in exports
    assert main(["soak", "status", "--json"]) == 0
