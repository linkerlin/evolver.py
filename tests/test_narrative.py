"""Tests for evolver.ops.narrative."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.ops import narrative as nar


@pytest.fixture
def isolated_evolver_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    yield tmp_path


def test_generate_narrative_success(isolated_evolver_env: Path) -> None:
    event = {
        "timestamp": "2026-01-01T00:00:00.000Z",
        "gene_id": "g1",
        "signals": ["stable_success_plateau"],
        "mutation": {"id": "m1", "category": "innovate", "risk_level": "low"},
        "blast_radius": {"files": 2, "lines": 42},
        "outcome": {"status": "success", "score": 1.0},
    }
    text = nar.generate_narrative(event)
    assert "g1" in text
    assert "success" in text
    assert "2 file(s)" in text


def test_generate_narrative_no_changes(isolated_evolver_env: Path) -> None:
    event = {
        "timestamp": "2026-01-01T00:00:00.000Z",
        "gene_id": "g1",
        "signals": [],
        "mutation": {},
        "blast_radius": {"files": 0, "lines": 0},
        "outcome": {"status": "success"},
    }
    text = nar.generate_narrative(event)
    assert "no file changes" in text


def test_append_narrative_creates_file(isolated_evolver_env: Path) -> None:
    event = {
        "timestamp": "2026-01-01T00:00:00.000Z",
        "gene_id": "g1",
        "signals": [],
        "mutation": {},
        "blast_radius": {},
        "outcome": {"status": "success"},
    }
    nar.append_narrative(event)
    path = isolated_evolver_env / "evolution" / "evolution_narrative.md"
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "g1" in content


def test_generate_reflection_failed_lessons(isolated_evolver_env: Path) -> None:
    event = {
        "timestamp": "2026-01-01T00:00:00.000Z",
        "id": "evt_1",
        "gene_id": "g1",
        "mutation": {"category": "repair"},
        "blast_radius": {"files": 15, "lines": 200},
        "outcome": {"status": "failed", "score": 0.0},
        "signals": ["log_error"],
    }
    refl = nar.generate_reflection(event)
    assert refl["outcome_status"] == "failed"
    assert "validation_failed" in refl["lessons"]
    assert "large_blast_radius" in refl["lessons"]


def test_record_narrative_and_reflection(isolated_evolver_env: Path) -> None:
    event = {
        "timestamp": "2026-01-01T00:00:00.000Z",
        "id": "evt_1",
        "gene_id": "g1",
        "mutation": {"category": "innovate"},
        "blast_radius": {"files": 1, "lines": 10},
        "outcome": {"status": "success", "score": 1.0},
        "signals": ["stable_success_plateau"],
    }
    result = nar.record_narrative_and_reflection(event)
    assert result["ok"] is True
    narrative_path = isolated_evolver_env / "evolution" / "evolution_narrative.md"
    reflection_path = isolated_evolver_env / "evolution" / "reflection_log.jsonl"
    assert narrative_path.exists()
    assert reflection_path.exists()
