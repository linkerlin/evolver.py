"""Tests for evolver.cli entry points."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from evolver.cli import main


@pytest.fixture
def isolated_evolver_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point all evolver state into tmp_path so tests do not touch ~/.evomap."""
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("EVOLVER_USER_LOCK", str(tmp_path / "user.lock"))
    yield tmp_path


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--version"])
    assert code == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("evolver ")


def test_cli_run_emits_prompt(isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["run"])
    assert code == 0
    captured = capsys.readouterr()
    assert "GENOME EVOLUTION PROTOCOL" in captured.out


def test_cli_solidify_without_state_fails(isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["solidify"])
    assert code == 1
    captured = capsys.readouterr()
    assert "no_pending_run" in captured.err


def test_cli_solidify_after_run_in_git_repo(isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    subprocess.run(["git", "init", "-b", "main", str(isolated_evolver_env)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(isolated_evolver_env), "config", "user.email", "test@example.com"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(isolated_evolver_env), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )

    code = main(["run"])
    assert code == 0

    code = main(["solidify"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Solidify succeeded" in captured.out


def test_cli_webui_token_generate_and_revoke(isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_HOME", str(isolated_evolver_env / ".evolver"))
    code = main(["webui-token", "--generate", "--role", "admin"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Token (admin):" in captured.out
    token = captured.out.split(": ")[1].strip()

    code = main(["webui-token"])
    assert code == 0
    captured = capsys.readouterr()
    assert "1 token(s)" in captured.out

    code = main(["webui-token", "--revoke", token])
    assert code == 0
    captured = capsys.readouterr()
    assert "Revoked." in captured.out
