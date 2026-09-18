"""Tests for evolver.gep.acceptance.orchestrator (Sprint A1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep.acceptance import orchestrator, t0_frozen
from evolver.gep.acceptance.orchestrator import (
    load_baseline,
    load_baseline_repeats,
    run_acceptance_gate,
    save_baseline,
)
from evolver.gep.acceptance.schemas import RepeatObs


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
    monkeypatch.setattr(orchestrator.t0_frozen, "load_snapshot", lambda _p: list(frozen_ids))
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
    def test_no_baseline_accepts_and_establishes(self, _stub_t0: Path, tmp_path: Path) -> None:
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


class TestLayerIdNormalization:
    """Round-21: the persisted baseline stores a full layer id back into
    t0_snapshot_hash; composing the next layer id must not double the
    ``T0_frozen@`` prefix (live events read
    ``T0_frozen@T0_frozen@<hash>``)."""

    def test_layer_id_from_persisted_layer_label(self, _stub_t0: Path, tmp_path: Path) -> None:
        result = run_acceptance_gate(
            cwd=tmp_path,
            snapshot_dir=tmp_path / "snap",
            baseline_t0_rate=0.75,
            repeats=1,
            baseline_t0_snapshot="T0_frozen@abc123",
        )
        assert result.layers[0].layer_id == "T0_frozen@abc123"

    def test_layer_id_from_snapshot_stem(self, _stub_t0: Path, tmp_path: Path) -> None:
        result = run_acceptance_gate(
            cwd=tmp_path,
            snapshot_dir=tmp_path / "snap",
            baseline_t0_rate=0.75,
            repeats=1,
            baseline_t0_snapshot="t0_abc123",
        )
        assert result.layers[0].layer_id == "T0_frozen@abc123"

    def test_layer_id_from_bare_hash(self, _stub_t0: Path, tmp_path: Path) -> None:
        result = run_acceptance_gate(
            cwd=tmp_path,
            snapshot_dir=tmp_path / "snap",
            baseline_t0_rate=0.75,
            repeats=1,
            baseline_t0_snapshot="abc123",
        )
        assert result.layers[0].layer_id == "T0_frozen@abc123"


class TestFlakeAdjudication:
    """Round-22/25: one flaky repeat must not become a verdict (soak
    false_kill_high, DEBUG #32). The frozen set is deterministic — ANY
    inter-repeat mismatch triggers one extra repeat; the majority value
    anchors the mean, minority observations are recorded but excluded.
    A consistent drop never triggers adjudication."""

    def test_flaky_repeat_trimmed_not_rejected(
        self, _stub_t0: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # repeat0 flakes to 2/4 (0.5), repeat1 measures 4/4, the adjudication
        # repeat corroborates 4/4 → the 0.5 observation is trimmed, the mean
        # returns to 1.0, and the phantom "regresses" verdict disappears.
        sequence = iter([(2, 4), (4, 4), (4, 4)])

        def fake_run(ids: list[str], _cwd: Path, **_kw: object) -> tuple[int, int]:
            return next(sequence)

        monkeypatch.setattr(orchestrator.t0_frozen, "run_pass_rate", fake_run)
        result = run_acceptance_gate(
            cwd=tmp_path,
            snapshot_dir=tmp_path / "snap",
            baseline_t0_rate=1.0,
            repeats=2,
        )
        layer = result.layers[0]
        assert layer.verdict == "unchanged"
        assert layer.candidate_mean == 1.0
        assert result.accepted is True
        assert layer.adjudication is not None
        assert layer.adjudication["trimmed"][0]["score"] == 0.5
        assert layer.adjudication["adjudication_repeat"]["score"] == 1.0

    def test_consistent_regression_still_rejects(
        self, _stub_t0: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Both repeats agree on 2/4 — a real regression, not noise. No
        # adjudication, no extra run, the rejection path is untouched.
        calls = {"n": 0}

        def fake_run(ids: list[str], _cwd: Path, **_kw: object) -> tuple[int, int]:
            calls["n"] += 1
            return (2, 4)

        monkeypatch.setattr(orchestrator.t0_frozen, "run_pass_rate", fake_run)
        result = run_acceptance_gate(
            cwd=tmp_path,
            snapshot_dir=tmp_path / "snap",
            baseline_t0_rate=1.0,
            repeats=2,
        )
        layer = result.layers[0]
        assert layer.verdict == "dropped"
        assert result.accepted is False
        assert layer.adjudication is None
        assert calls["n"] == 2  # exactly the requested repeats

    def test_consistent_repeats_skip_adjudication(
        self, _stub_t0: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}

        def fake_run(ids: list[str], _cwd: Path, **_kw: object) -> tuple[int, int]:
            calls["n"] += 1
            return (4, 4)

        monkeypatch.setattr(orchestrator.t0_frozen, "run_pass_rate", fake_run)
        result = run_acceptance_gate(
            cwd=tmp_path,
            snapshot_dir=tmp_path / "snap",
            baseline_t0_rate=1.0,
            repeats=2,
        )
        assert result.layers[0].adjudication is None
        assert calls["n"] == 2

    def test_single_test_flake_triggers_adjudication(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Round-25 (DEBUG #35 tail): a repeat short by exactly ONE test
        # (3517 vs 3518 of 3519, spread 0.00028) previously sailed under
        # the 0.05 bar and dragged the mean into a phantom "dropped".
        # Deterministic suite ⇒ any mismatch adjudicates; majority anchors.
        from evolver.gep.acceptance.schemas import RepeatObs

        n = 3519
        obs = [
            RepeatObs(repeat_index=0, score=3517 / n, denominator=n),
            RepeatObs(repeat_index=1, score=3518 / n, denominator=n),
        ]

        def fake_extra(_ids: list[str], _cwd: Path, *, repeats: int) -> list[RepeatObs]:
            return [RepeatObs(repeat_index=9, score=3518 / n, denominator=n)]

        monkeypatch.setattr(orchestrator, "_run_t0_repeats", fake_extra)
        kept, info = orchestrator._adjudicate_flakes([], tmp_path, obs)
        assert [o.score for o in kept] == [3518 / n, 3518 / n]
        assert info is not None
        assert info["trigger"] == "repeat_mismatch"
        assert info["trimmed"][0]["score"] == 3517 / n

    def test_no_majority_keeps_everything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Continuous flakiness (three distinct values): conservative — all
        # observations stay in the mean, verdict fails toward rejection.
        from evolver.gep.acceptance.schemas import RepeatObs

        obs = [
            RepeatObs(repeat_index=0, score=0.9, denominator=10),
            RepeatObs(repeat_index=1, score=0.8, denominator=10),
        ]

        def fake_extra(_ids: list[str], _cwd: Path, *, repeats: int) -> list[RepeatObs]:
            return [RepeatObs(repeat_index=9, score=0.7, denominator=10)]

        monkeypatch.setattr(orchestrator, "_run_t0_repeats", fake_extra)
        kept, info = orchestrator._adjudicate_flakes([], tmp_path, obs)
        assert len(kept) == 3
        assert info is not None
        assert info["trimmed"] == []


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
        # Round-25: mismatched repeats now always adjudicate
        # (TestFlakeAdjudication); identical repeats exercise the plain
        # mean-over-repeats machinery without an extra run.
        sequence = iter([(3, 4), (3, 4), (3, 4)])

        def fake_run(_ids: list[str], _cwd: Path, **_kw: object) -> tuple[int, int]:
            return next(sequence)

        monkeypatch.setattr(orchestrator.t0_frozen, "run_pass_rate", fake_run)
        result = run_acceptance_gate(
            cwd=tmp_path,
            snapshot_dir=tmp_path / "snap",
            baseline_t0_rate=0.75,
            repeats=3,
        )
        # mean of three identical 0.75 repeats = 0.75 -> unchanged vs 0.75
        assert result.layers[0].candidate_mean == pytest.approx(0.75)
        assert len(result.layers[0].candidate_repeats) == 3


class TestBilateralRepeats:
    def test_save_and_load_baseline_repeats_round_trip(self, tmp_path: Path) -> None:
        p = tmp_path / "base.json"
        obs = [
            RepeatObs(repeat_index=0, score=0.75, denominator=4),
            RepeatObs(repeat_index=1, score=0.75, denominator=4),
        ]
        save_baseline(p, t0_pass_rate=0.75, snapshot_hash="h1", repeats=obs)
        loaded = load_baseline_repeats(p)
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[0].score == 0.75
        assert loaded[1].repeat_index == 1

    def test_run_acceptance_gate_with_baseline_repeats(
        self, _stub_t0: Path, tmp_path: Path
    ) -> None:
        base_obs = [
            RepeatObs(repeat_index=0, score=0.75, denominator=4),
            RepeatObs(repeat_index=1, score=0.75, denominator=4),
        ]
        result = run_acceptance_gate(
            cwd=tmp_path,
            snapshot_dir=tmp_path / "snap",
            baseline_t0_rate=None,
            baseline_repeats=base_obs,
            repeats=1,
        )
        assert result.accepted is True
        layer = result.layers[0]
        assert len(layer.baseline_repeats) == 2
        assert layer.baseline_mean == 0.75

    def test_run_acceptance_gate_with_baseline_cwd(
        self, _stub_t0: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base_dir = tmp_path / "baseline_cwd"
        base_dir.mkdir()
        cand_dir = tmp_path / "cand_cwd"
        cand_dir.mkdir()

        def fake_run(ids: list[str], cwd: Path, **_kw: object) -> tuple[int, int]:
            if cwd == base_dir:
                return (3, len(ids))  # 0.75
            return (4, len(ids))  # 1.0

        monkeypatch.setattr(orchestrator.t0_frozen, "run_pass_rate", fake_run)
        result = run_acceptance_gate(
            cwd=cand_dir,
            snapshot_dir=tmp_path / "snap",
            baseline_t0_rate=None,
            baseline_cwd=base_dir,
            repeats=2,
        )
        assert result.accepted is True
        layer = result.layers[0]
        assert layer.baseline_mean == 0.75
        assert layer.candidate_mean == 1.0
        assert layer.verdict == "improved"
