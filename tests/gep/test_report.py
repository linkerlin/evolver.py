"""S27.4 evolution report — verdicts, r_best ledger, negatives as-is."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep.report import build_report


@pytest.fixture
def report_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    evo = tmp_path / "evo"
    gep = tmp_path / "gep"
    evo.mkdir()
    gep.mkdir()
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(gep))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))

    events = [
        {
            "type": "EvolutionEvent",
            "run_id": "r1",
            "timestamp": "t1",
            "outcome": {"status": "success", "score": 0.75},
            "fitness_gate": {"verdict": "improved", "score": 0.75, "r_best": 0.75},
        },
        {
            "type": "EvolutionEvent",
            "run_id": "r2",
            "timestamp": "t2",
            "outcome": {"status": "failed", "score": 0.0, "error": "validation_failed"},
        },
        {
            "type": "EvolutionEvent",
            "run_id": "r3",
            "timestamp": "t3",
            "outcome": {"status": "success", "score": 0.5},
            "fitness_gate": {"verdict": "no_improvement", "score": 0.5, "r_best": 0.75},
        },
        {"type": "cycle_start", "timestamp": "t0"},
    ]
    (gep / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )
    (evo / "evolution_fitness_state.json").write_text(
        json.dumps(
            {
                "domains": {
                    "cascade": {
                        "baseline": 0.5,
                        "r_best": 0.75,
                        "history": [{}, {}],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    wiki = evo / "wiki"
    (wiki).mkdir()
    (wiki / "log.md").write_text(
        "# Decision Log\n- [t] accepted r1\n- [t] accepted r9\n", encoding="utf-8"
    )
    (wiki / "skill-impact.md").write_text(
        "# Skill Impact\n## t2 — validation_failed\nbody\n", encoding="utf-8"
    )
    return evo


def test_report_counts_and_ledger(report_ws: Path) -> None:
    md = build_report()
    assert "- EvolutionEvents: 3" in md
    assert "- success: 2 (unvalidated: 0)" in md
    assert "- failed: 1" in md
    assert "no_improvement: 1" in md
    assert "| cascade | 0.5 | 0.75 | 2 |" in md
    assert "decision-log entries: 2" in md
    assert "skill-impact entries (rejected/non-improving): 1" in md


def test_report_negatives_as_is(report_ws: Path) -> None:
    md = build_report()
    assert "failed: validation_failed" in md
    assert "run=r2" in md
    assert "no_improvement: score=0.5 r_best=0.75" in md
    assert "run=r3" in md
    # most recent first: r3 (no_improvement) appears before r2 (failed)
    assert md.index("run=r3") < md.index("run=r2")


def test_report_empty_state_is_honest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    md = build_report()
    assert "No measured fitness yet" in md
    assert "None in window" in md
