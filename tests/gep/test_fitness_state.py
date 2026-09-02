"""S26.3 fitness ledger: strict-improvement gating, domain-separated (R_val > R_best)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep.fitness_state import (
    CASCADE_DOMAIN,
    fitness_state_path,
    load_domain,
    load_fitness_state,
    record_measurement,
)


@pytest.fixture
def evo_dir(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = temp_workspace / "memory" / "evolution"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EVOLUTION_DIR", str(d))
    return d


def test_default_state_when_missing(evo_dir: Path) -> None:
    assert load_fitness_state() == {"domains": {}}


def test_corrupt_state_degrades(evo_dir: Path) -> None:
    fitness_state_path().write_text("{not json", encoding="utf-8")
    assert load_fitness_state() == {"domains": {}}


def test_first_measurement_establishes_baseline(evo_dir: Path) -> None:
    v = record_measurement(0.8, source="solidify:run-1")
    assert v is not None
    assert v["verdict"] == "baseline_established"
    assert v["domain"] == CASCADE_DOMAIN
    assert load_domain("cascade")["r_best"] == 0.8


def test_strict_improvement_only(evo_dir: Path) -> None:
    record_measurement(0.8, source="solidify:a")
    same = record_measurement(0.8, source="solidify:b")
    assert same is not None and same["verdict"] == "no_improvement"
    assert load_domain("cascade")["r_best"] == 0.8
    lower = record_measurement(0.5, source="solidify:c")
    assert lower is not None and lower["verdict"] == "no_improvement"
    better = record_measurement(0.8001, source="solidify:d")
    assert better is not None and better["verdict"] == "improved"
    assert load_domain("cascade")["r_best"] == 0.8001


def test_unmeasured_never_touches_ledger(evo_dir: Path) -> None:
    record_measurement(0.8, source="solidify:a")
    assert record_measurement(None, source="solidify:b") is None
    domain = load_domain("cascade")
    assert domain["r_best"] == 0.8
    assert len(domain["history"]) == 1


def test_domains_keep_incomparable_scales_apart(evo_dir: Path) -> None:
    """THE review fix: a cascade 1.0 must never lock out a bench 0.83 —
    cascade stage-progress and bench task-rate are different measurement
    domains and gate independently."""
    cascade = record_measurement(1.0, source="solidify:run-1")
    assert cascade is not None and cascade["domain"] == CASCADE_DOMAIN
    bench = record_measurement(0.83, source="bench:health")
    assert bench is not None
    assert bench["domain"] == "bench:health"
    # the bench measurement is NOT judged against cascade's r_best
    assert bench["verdict"] == "baseline_established"
    assert bench["r_best"] == 0.83
    # each domain evolves independently
    assert load_domain("cascade")["r_best"] == 1.0
    assert record_measurement(0.9, source="bench:health")["verdict"] == "improved"
    assert record_measurement(0.99, source="solidify:x")["verdict"] == "no_improvement"


def test_pack_splits_are_separate_domains(evo_dir: Path) -> None:
    record_measurement(0.5, source="bench:pack:val")
    record_measurement(1.0, source="bench:pack:train")
    assert load_domain("bench:pack:val")["r_best"] == 0.5
    assert load_domain("bench:pack:train")["r_best"] == 1.0


def test_history_is_persisted(evo_dir: Path) -> None:
    record_measurement(0.8, source="solidify:a")
    record_measurement(0.9, source="solidify:b")
    raw = json.loads(fitness_state_path().read_text(encoding="utf-8"))
    assert [h["verdict"] for h in raw["domains"]["cascade"]["history"]] == [
        "baseline_established",
        "improved",
    ]


def test_legacy_state_migrates_to_cascade_domain(evo_dir: Path) -> None:
    """Pre-domains ledgers were cascade-only by construction — migrate."""
    fitness_state_path().write_text(
        json.dumps({"baseline": 0.7, "r_best": 0.9, "history": [{"verdict": "old"}]}),
        encoding="utf-8",
    )
    state = load_fitness_state()
    assert state["domains"][CASCADE_DOMAIN]["r_best"] == 0.9
    # and the domain continues from there
    verdict = record_measurement(0.95, source="solidify:post-migration")
    assert verdict is not None and verdict["verdict"] == "improved"
