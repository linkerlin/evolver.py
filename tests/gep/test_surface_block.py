"""Tests for surface block rendering + candidate surface_ref (Sprint A2)."""

from __future__ import annotations

from pathlib import Path

from evolver.gep.candidate_eval import Candidate
from evolver.gep.surface import (
    SurfaceSnapshot,
    capture_surface,
    render_surface_block,
    surface_delta,
)


def _snap(*files: str) -> SurfaceSnapshot:
    return SurfaceSnapshot(files=dict.fromkeys(files, "hash"), snapshot_id="sid")


class TestRenderSurfaceBlock:
    def test_empty_returns_empty(self) -> None:
        assert render_surface_block(_snap()) == ""

    def test_renders_baseline(self) -> None:
        block = render_surface_block(_snap("a.py", "b.py"))
        assert "PROPOSER SURFACE" in block
        assert "sid" in block
        assert "a.py" in block
        assert "b.py" in block

    def test_renders_delta(self) -> None:
        block = render_surface_block(
            _snap("a.py", "b.py"),
            {"added": ["c.py"], "removed": [], "changed": ["a.py"]},
        )
        assert "changed=a.py" in block
        assert "added=c.py" in block

    def test_no_delta_no_drift_line(self) -> None:
        block = render_surface_block(_snap("a.py"))
        assert "eval-surface drift" not in block


class TestCandidateSurfaceRef:
    def test_default_none(self) -> None:
        assert Candidate(diff_text="x").surface_ref is None

    def test_round_trip(self) -> None:
        cand = Candidate(diff_text="x", surface_ref="sid123")
        assert cand.surface_ref == "sid123"
        assert cand.candidate_id  # property unaffected


class TestSurfaceDeltaRoundTrip:
    def test_capture_and_delta(self, tmp_path: Path) -> None:
        p = tmp_path / "a.py"
        p.write_text("x\n", encoding="utf-8")
        base = capture_surface([p], root=tmp_path)
        p.write_text("y\n", encoding="utf-8")
        delta = surface_delta(base, capture_surface([p], root=tmp_path))
        assert delta["changed"] == ["a.py"]
        block = render_surface_block(base, delta)
        assert "changed=a.py" in block
