"""Tests for dispatch surface anchoring (Sprint A2)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from evolver.evolve.pipeline.dispatch import dispatch_phase
from evolver.gep.surface import load_snapshot


@pytest.fixture
def _surface_ws(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path]:
    """A workspace with one surface file + isolated GEP assets dir."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "src").mkdir()
    (ws / "src" / "surface.py").write_text("x = 1\n", encoding="utf-8")
    gep = tmp_path / "gep"
    gep.mkdir()
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(ws))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(ws))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(gep))
    return ws, gep


def _minimal_ctx() -> dict:
    return {
        "cycle_id": "c1",
        "run_id": "r1",
        "signals": ["log_error"],
        "selected_gene": {"id": "g1"},
        "mutation": {"id": "m1", "validation": []},
        "skip_hub_calls": True,
        "surface_files": ["src/surface.py"],
        "scan_time_iso": "2026-01-01T00:00:00Z",
    }


class TestDispatchSurfaceAnchor:
    def test_flag_off_no_anchoring(
        self,
        _surface_ws: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SURFACE_DECOUPLE", "0")
        ws, _gep = _surface_ws
        result = asyncio.run(dispatch_phase(_minimal_ctx()))
        assert "proposer_surface_block" not in result

    def test_flag_on_anchors_and_persists_baseline(
        self,
        _surface_ws: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SURFACE_DECOUPLE", "1")
        ws, gep = _surface_ws
        result = asyncio.run(dispatch_phase(_minimal_ctx()))
        block = result["proposer_surface_block"]
        assert "PROPOSER SURFACE" in block
        assert "src/surface.py" in block
        # baseline persisted to disk for cross-cycle stability
        baseline = load_snapshot(gep / "surfaces" / "baseline.json")
        assert baseline is not None
        assert "src/surface.py" in baseline.files

    def test_baseline_stable_across_cycles(
        self,
        _surface_ws: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SURFACE_DECOUPLE", "1")
        ws, gep = _surface_ws
        asyncio.run(dispatch_phase(_minimal_ctx()))
        baseline_id = load_snapshot(gep / "surfaces" / "baseline.json").snapshot_id
        # evolve the surface, run again → baseline UNCHANGED, drift reported
        (ws / "src" / "surface.py").write_text("x = 2\n", encoding="utf-8")
        result2 = asyncio.run(dispatch_phase(_minimal_ctx()))
        baseline2 = load_snapshot(gep / "surfaces" / "baseline.json")
        assert baseline2.snapshot_id == baseline_id  # stable parent
        assert "changed=src/surface.py" in result2["proposer_surface_block"]

    def test_no_surface_files_noop(
        self,
        _surface_ws: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_SURFACE_DECOUPLE", "1")
        ws, _gep = _surface_ws
        ctx = _minimal_ctx()
        del ctx["surface_files"]
        result = asyncio.run(dispatch_phase(ctx))
        assert "proposer_surface_block" not in result
