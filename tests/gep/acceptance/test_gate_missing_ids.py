"""Soak round-3 fix: the T0 gate must detect DELETED frozen tests.

Re-freezing the current test set per run made deleted tests vanish from the
denominator — the gate was blind to test deletion. With a baseline present,
frozen IDs now load from the persisted baseline snapshot.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep.acceptance.orchestrator import (
    load_baseline_payload,
    run_acceptance_gate,
    save_baseline,
)


@pytest.fixture
def t0_ws(temp_workspace: Path) -> Path:
    (t0_ws := temp_workspace / "pkg").mkdir()
    (t0_ws / "conftest.py").write_text("", encoding="utf-8")
    (t0_ws / "tests").mkdir()
    (t0_ws / "tests" / "test_a.py").write_text(
        "def test_a() -> None:\n    assert True\n", encoding="utf-8"
    )
    return t0_ws


def _establish(t0_ws: Path, snapshot_dir: Path, baseline_path: Path) -> None:
    result = run_acceptance_gate(
        cwd=t0_ws, snapshot_dir=snapshot_dir, baseline_t0_rate=None, repeats=1
    )
    assert result.accepted is True
    assert result.reason == "t0_baseline_established"
    layer = result.layers[0]
    save_baseline(baseline_path, layer.candidate_mean, layer.layer_id)


class TestDeletedTests:
    def test_baseline_ids_frozen_across_runs(
        self, t0_ws: Path, tmp_path: Path
    ) -> None:
        snapshot_dir = tmp_path / "snaps"
        baseline_path = tmp_path / "baseline.json"
        _establish(t0_ws, snapshot_dir, baseline_path)

        # add a second test, still all green -> accepted, no regression
        (t0_ws / "tests" / "test_b.py").write_text(
            "def test_b() -> None:\n    assert True\n", encoding="utf-8"
        )
        payload = load_baseline_payload(baseline_path)
        result = run_acceptance_gate(
            cwd=t0_ws,
            snapshot_dir=snapshot_dir,
            baseline_t0_rate=float(payload["t0_pass_rate"]),
            baseline_t0_snapshot=payload["t0_snapshot_hash"],
            repeats=1,
        )
        assert result.accepted is True

    def test_deleted_frozen_test_rejected(self, t0_ws: Path, tmp_path: Path) -> None:
        snapshot_dir = tmp_path / "snaps"
        baseline_path = tmp_path / "baseline.json"
        _establish(t0_ws, snapshot_dir, baseline_path)

        # delete the frozen test; replace with a different passing one
        (t0_ws / "tests" / "test_a.py").unlink()
        (t0_ws / "tests" / "test_b.py").write_text(
            "def test_b() -> None:\n    assert True\n", encoding="utf-8"
        )
        payload = load_baseline_payload(baseline_path)
        result = run_acceptance_gate(
            cwd=t0_ws,
            snapshot_dir=snapshot_dir,
            baseline_t0_rate=float(payload["t0_pass_rate"]),
            baseline_t0_snapshot=payload["t0_snapshot_hash"],
            repeats=1,
        )
        assert result.accepted is False
        assert result.reason == "T0_frozen_regressed"

    def test_missing_snapshot_falls_back_to_discovery(
        self, t0_ws: Path, tmp_path: Path
    ) -> None:
        snapshot_dir = tmp_path / "snaps"
        baseline_path = tmp_path / "baseline.json"
        _establish(t0_ws, snapshot_dir, baseline_path)
        # corrupt/absent snapshot file -> degraded discovery path, still runs
        for p in snapshot_dir.glob("t0_*.txt"):
            p.unlink()
        payload = load_baseline_payload(baseline_path)
        result = run_acceptance_gate(
            cwd=t0_ws,
            snapshot_dir=snapshot_dir,
            baseline_t0_rate=float(payload["t0_pass_rate"]),
            baseline_t0_snapshot=payload["t0_snapshot_hash"],
            repeats=1,
        )
        assert result.accepted is True  # discovery re-froze current green set
