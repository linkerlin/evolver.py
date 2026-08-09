"""Tests for evolver.gep.surface (Sprint A2)."""

from __future__ import annotations

from pathlib import Path

from evolver.gep.surface import (
    SurfaceSnapshot,
    capture_surface,
    fingerprint_files,
    load_snapshot,
    save_snapshot,
    surface_delta,
)


class TestFingerprintFiles:
    def test_hashes_content(self, tmp_path: Path) -> None:
        p = tmp_path / "a.py"
        p.write_text("x = 1\n", encoding="utf-8")
        fp = fingerprint_files([p])
        assert fp["a.py"] and fp["a.py"] != "<missing>"

    def test_content_change_changes_hash(self, tmp_path: Path) -> None:
        p = tmp_path / "a.py"
        p.write_text("x = 1\n", encoding="utf-8")
        fp1 = fingerprint_files([p])
        p.write_text("x = 2\n", encoding="utf-8")
        fp2 = fingerprint_files([p])
        assert fp1["a.py"] != fp2["a.py"]

    def test_missing_file_marked(self, tmp_path: Path) -> None:
        fp = fingerprint_files([tmp_path / "nope.py"])
        assert fp["nope.py"] == "<missing>"


class TestCaptureSurface:
    def test_snapshot_id_stable(self, tmp_path: Path) -> None:
        p = tmp_path / "a.py"
        p.write_text("x\n", encoding="utf-8")
        s1 = capture_surface([p], root=tmp_path)
        s2 = capture_surface([p], root=tmp_path)
        assert s1.snapshot_id == s2.snapshot_id
        assert s1.format == "evolver.surface_snapshot.v0"

    def test_snapshot_id_changes_on_edit(self, tmp_path: Path) -> None:
        p = tmp_path / "a.py"
        p.write_text("x\n", encoding="utf-8")
        s1 = capture_surface([p], root=tmp_path)
        p.write_text("y\n", encoding="utf-8")
        s2 = capture_surface([p], root=tmp_path)
        assert s1.snapshot_id != s2.snapshot_id


class TestSaveLoad:
    def test_round_trip(self, tmp_path: Path) -> None:
        p = tmp_path / "src" / "a.py"
        p.parent.mkdir()
        p.write_text("x\n", encoding="utf-8")
        snap = capture_surface([p], root=tmp_path)
        path = tmp_path / "snap.json"
        save_snapshot(snap, path)
        loaded = load_snapshot(path)
        assert loaded is not None
        assert loaded.snapshot_id == snap.snapshot_id
        assert loaded.files == snap.files

    def test_missing_returns_none(self, tmp_path: Path) -> None:
        assert load_snapshot(tmp_path / "nope.json") is None

    def test_corrupt_returns_none(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("{broken", encoding="utf-8")
        assert load_snapshot(p) is None


class TestSurfaceDelta:
    def _base(self, tmp_path: Path) -> tuple[Path, SurfaceSnapshot]:
        a = tmp_path / "a.py"
        a.write_text("x\n", encoding="utf-8")
        return a, capture_surface([a], root=tmp_path)

    def test_changed(self, tmp_path: Path) -> None:
        a, base = self._base(tmp_path)
        a.write_text("y\n", encoding="utf-8")
        delta = surface_delta(base, capture_surface([a], root=tmp_path))
        assert delta["changed"] == ["a.py"]
        assert delta["added"] == []
        assert delta["removed"] == []

    def test_added_removed(self, tmp_path: Path) -> None:
        a, base = self._base(tmp_path)
        b = tmp_path / "b.py"
        b.write_text("z\n", encoding="utf-8")
        current = capture_surface([a, b], root=tmp_path)
        delta = surface_delta(base, current)
        assert delta["added"] == ["b.py"]
        a.unlink()
        delta2 = surface_delta(base, capture_surface([b], root=tmp_path))
        assert delta2["removed"] == ["a.py"]

    def test_identical(self, tmp_path: Path) -> None:
        a, base = self._base(tmp_path)
        delta = surface_delta(base, capture_surface([a], root=tmp_path))
        assert delta == {"added": [], "removed": [], "changed": []}
