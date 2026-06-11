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
    assert "No events recorded" in capsys.readouterr().out


def test_asset_log_shows_events(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from evolver.gep.asset_store import append_event_jsonl

    append_event_jsonl(
        {
            "type": "EvolutionEvent",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "gene_id": "g1",
            "outcome": {"status": "success"},
            "blast_radius": {"files": 2, "lines": 42},
        }
    )
    code = main(["asset-log"])
    captured = capsys.readouterr()
    assert code == 0
    assert "gene=g1" in captured.out
