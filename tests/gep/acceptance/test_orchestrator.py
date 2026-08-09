"""Tests for evolver.gep.acceptance.orchestrator (Sprint A1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep.acceptance import orchestrator, t0_frozen
from evolver.gep.acceptance.orchestrator import (
    load_baseline,
    run_acceptance_gate,
    save_baseline,
)


@pytest.fixture
def _stub_t0(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Stub discover/run so the orchestrator does no real subprocess.

    Frozen set = 4 test IDs. The candidate pass count is configurable per
    test via the ``_candidate_passed`` attribute on the stub.
    """
    frozen_ids = [f"mod::test_{i}" for i in range(4)]

    def fake_discover(_cwd: Path) -> list[str]:
        return list(frozen_ids)

    state = {"passed": 4}

    def fake_run(ids: list[str], _cwd: Path, **_kw: object) -> tuple[int, int]:
        return (state["passed"], len(ids))

    monkeypatch.setattr(t0_frozen, "discover_test_ids", fake_discover)
    monkeypatch.setattr(t0_frozen, "run_pass_rate", fake_run)
    # The orchestrator imports t0_frozen as a module, so it sees these stubs.
    monkeypatch.setattr(orchestrator.t0_frozen, "discover_test_ids", fake_discover)
    monkeypatch.setattr(orchestrator.t0_frozen, "run_pass_rate", fake_run)
    monkeypatch.setattr(orchestrator.t0_frozen, "freeze_snapshot", lambda _ids, d: d / "snap.txt")
    monkeypatch.setattr(
        orchestrator.t0_frozen, "load_snapshot", lambda _p: list(frozen_ids)
    )
    return tmp_path


class TestBaselinePersistence:
    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        assert load_baseline(tmp_path / "none.json") is None

    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        p = tmp_path / "base.json"
        save_baseline(p, t0_pass_rate=0.75, snapshot_hash="abc123")
        assert load_baseline(p) == 0.75
        payload = json.loads(p.read_text(encoding="utf-8"))
        assert payload["t0_snapshot_hash"] == "abc123"

    def test_load_corrupt_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        assert load_baseline(p) is None


class TestEstablishingMode:
    def test_no_baseline_accepts_and_establishes(
        self, _stub_t0: Path, tmp_path: Path
    ) -> None:
        result = run_acceptance_gate(
            cwd=tmp_path,
            snapshot_dir=tmp_path / "snap",
            baseline_t0_rate=None,
            repeats=1,
        )
        assert result.accepted is True
        assert result.reason == "t0_baseline_established"
        assert len(result.layers) == 1
        assert result.layers[0].kind == "T0_frozen"


class TestDegradedT0Only:
    def test_no_regression_accepts(self, _stub_t0: Path, tmp_path: Path) -> None:
        result = run_acceptance_gate(
            cwd=tmp_path,
            snapshot_dir=tmp_path / "snap",
            baseline_t0_rate=0.75,  # 3/4
            repeats=1,
        )
        # stub defaults to 4/4 passed → improved over 0.75 → no regression
        assert result.accepted is True
        assert result.reason == "t0_only_no_regression"
        assert result.layers[0].verdict == "improved"
        assert result.layers[0].candidate_mean == 1.0

    def test_regression_rejects(
        self,
        _stub_t0: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # force candidate to pass only 2/4 → drop vs baseline 0.75
        def fake_run(ids: list[str], _cwd: Path, **_kw: object) -> tuple[int, int]:
            return (2, len(ids))

        monkeypatch.setattr(orchestrator.t0_frozen, "run_pass_rate", fake_run)
        result = run_acceptance_gate(
            cwd=tmp_path,
            snapshot_dir=tmp_path / "snap",
            baseline_t0_rate=0.75,
            repeats=1,
        )
        assert result.accepted is False
        assert result.reason == "T0_frozen_regressed"
        assert result.layers[0].verdict == "dropped"
        assert result.layers[0].candidate_mean == 0.5

    def test_unchanged_within_epsilon(
        self,
        _stub_t0: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # candidate 3/4 = 0.75, baseline 0.75 → unchanged
        def fake_run(ids: list[str], _cwd: Path, **_kw: object) -> tuple[int, int]:
            return (3, len(ids))

        monkeypatch.setattr(orchestrator.t0_frozen, "run_pass_rate", fake_run)
        result = run_acceptance_gate(
            cwd=tmp_path,
            snapshot_dir=tmp_path / "snap",
            baseline_t0_rate=0.75,
            repeats=1,
        )
        # unchanged → no regression → degraded accept
        assert result.accepted is True
        assert result.layers[0].verdict == "unchanged"


class TestRepeatsAveraging:
    def test_multiple_repeats_averaged(
        self,
        _stub_t0: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # cycle through 3/4, 4/4, 2/4 across repeats
        sequence = iter([(3, 4), (4, 4), (2, 4)])

        def fake_run(_ids: list[str], _cwd: Path, **_kw: object) -> tuple[int, int]:
            return next(sequence)

        monkeypatch.setattr(orchestrator.t0_frozen, "run_pass_rate", fake_run)
        result = run_acceptance_gate(
            cwd=tmp_path,
            snapshot_dir=tmp_path / "snap",
            baseline_t0_rate=0.75,
            repeats=3,
        )
        # mean = (0.75 + 1.0 + 0.5) / 3 = 0.75 → unchanged vs 0.75
        assert result.layers[0].candidate_mean == pytest.approx(0.75)
        assert len(result.layers[0].candidate_repeats) == 3
