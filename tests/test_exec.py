"""Tests for evolver.cli exec command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.cli import main


@pytest.fixture
def isolated_evolver_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    yield tmp_path


def test_exec_with_cmd(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["exec", "--cmd", "echo hello_exec"])
    captured = capsys.readouterr()
    assert code == 0
    assert "hello_exec" in captured.out


def test_exec_no_cmd_no_state(isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["exec"])
    captured = capsys.readouterr()
    assert code == 0
    assert "No pending solidify state" in captured.out


def test_exec_runs_validation(isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    state = {
        "last_run": {
            "run_id": "r1",
            "mutation": {
                "validation": ["echo validation_ok"],
            },
        }
    }
    state_path = isolated_evolver_env / "evolution" / "evolution_solidify_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    code = main(["exec"])
    captured = capsys.readouterr()
    assert code == 0
    assert "validation_ok" in captured.out
