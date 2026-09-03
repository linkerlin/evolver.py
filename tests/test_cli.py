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


def test_cli_run_emits_prompt(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["run"])
    assert code == 0
    captured = capsys.readouterr()
    assert "GENOME EVOLUTION PROTOCOL" in captured.out


def test_cli_solidify_without_state_fails(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["solidify"])
    assert code == 1
    captured = capsys.readouterr()
    assert "no_pending_run" in captured.err


def test_cli_hitl_list_approve_flow(
    isolated_evolver_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EvoX concept harvest: `evolver hitl list/approve/reject` (v1.100.0)."""
    monkeypatch.setattr("evolver.config.HITL_MODE", "on")
    from evolver.gep.hitl import request_approval

    assert main(["hitl", "list"]) == 0
    assert "No pending HITL approvals." in capsys.readouterr().out

    req = request_approval(subject="cli_test:s1", risk_reason="demo risk")
    assert main(["hitl", "list"]) == 0
    assert req["request_id"] in capsys.readouterr().out

    assert main(["hitl", "approve", "--id", req["request_id"], "--note", "ok"]) == 0
    assert "approved" in capsys.readouterr().out

    # Already decided — second resolution fails cleanly.
    assert main(["hitl", "reject", "--id", req["request_id"]]) == 1
    assert "not_pending" in capsys.readouterr().err


def test_cli_supervise_flow(isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """HOTL supervision via CLI (v1.101.0): status/pause/direct/resume."""
    assert main(["supervise", "status"]) == 0
    assert '"state": "running"' in capsys.readouterr().out

    assert main(["supervise", "pause", "--reason", "hold"]) == 0
    assert '"state": "paused"' in capsys.readouterr().out

    assert main(["supervise", "direct", "优先稳定测试"]) == 0
    assert "directive_id" in capsys.readouterr().out

    from evolver.gep.asset_store import consume_pending_signals

    assert any(s.startswith("supervision:directive:") for s in consume_pending_signals())

    assert main(["supervise", "resume"]) == 0
    assert '"state": "running"' in capsys.readouterr().out


def test_cli_solidify_after_run_in_git_repo(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    subprocess.run(
        ["git", "init", "-b", "main", str(isolated_evolver_env)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "-C", str(isolated_evolver_env), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(isolated_evolver_env), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )

    code = main(["run"])
    assert code == 0

    code = main(["solidify"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Solidify succeeded" in captured.out


def test_cli_webui_token_generate_and_revoke(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
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
