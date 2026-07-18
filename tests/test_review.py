"""Tests for evolver.cli review and asset-log commands."""

from __future__ import annotations

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


def test_review_no_state(isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["review"])
    assert code == 0
    assert "No pending solidify state" in capsys.readouterr().out


def test_asset_log_empty(isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["asset-log"])
    assert code == 0
    out = capsys.readouterr().out
    assert "asset_call_log.jsonl" in out
    assert "No entries found" in out


def test_asset_log_shows_call_entries(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # D2: asset-log must read asset_call_log.jsonl, not events.jsonl.
    from evolver.gep.asset_call_log import log_asset_call

    log_asset_call(
        {
            "run_id": "r1",
            "action": "asset_reuse",
            "asset_id": "sha256:abc123",
            "signals": ["log_error"],
        }
    )
    code = main(["asset-log"])
    captured = capsys.readouterr()
    assert code == 0
    assert "asset_reuse: 1" in captured.out
    assert "run=r1" in captured.out
