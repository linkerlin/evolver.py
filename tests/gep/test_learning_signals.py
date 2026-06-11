"""Tests for evolver.gep.learning_signals."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.gep.learning_signals import (
    detect_lock_conflicts,
    detect_missing_annotations,
    detect_platform_signals,
    gather_all_learning_signals,
)


class TestDetectPlatformSignals:
    def test_returns_list(self):
        signals = detect_platform_signals()
        assert isinstance(signals, list)

    def test_contains_platform_signal(self):
        signals = detect_platform_signals()
        types = {s["type"] for s in signals}
        assert "platform_warning" in types or "python_version" in types


class TestDetectLockConflicts:
    def test_no_lock_files(self, tmp_path: Path):
        signals = detect_lock_conflicts(tmp_path)
        assert signals == []

    def test_uv_lock_conflict_marker(self, tmp_path: Path):
        (tmp_path / "uv.lock").write_text("some text with CONFLICT marker")
        signals = detect_lock_conflicts(tmp_path)
        assert len(signals) == 1
        assert signals[0]["type"] == "dependency_conflict"

    def test_package_lock_corrupted(self, tmp_path: Path):
        (tmp_path / "package-lock.json").write_text("{}")
        signals = detect_lock_conflicts(tmp_path)
        assert len(signals) == 1
        assert "corrupted" in signals[0]["message"]

    def test_package_lock_valid(self, tmp_path: Path):
        (tmp_path / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3}))
        signals = detect_lock_conflicts(tmp_path)
        assert signals == []

    def test_package_lock_unreadable(self, tmp_path: Path):
        (tmp_path / "package-lock.json").write_text("not json")
        signals = detect_lock_conflicts(tmp_path)
        assert len(signals) == 1
        assert "unreadable" in signals[0]["message"]


class TestDetectMissingAnnotations:
    def test_empty_dir(self, tmp_path: Path):
        signals = detect_missing_annotations(tmp_path)
        assert signals == []

    def test_detects_missing(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "bad.py").write_text("x = 1\n")
        (src / "good.py").write_text("from __future__ import annotations\nx = 1\n")
        signals = detect_missing_annotations(tmp_path)
        assert len(signals) == 1
        assert "bad.py" in signals[0]["file"]

    def test_ignores_dotfiles(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        (src / ".hidden.py").write_text("x = 1\n")
        signals = detect_missing_annotations(tmp_path)
        assert signals == []

    def test_limits_to_top_10(self, tmp_path: Path):
        src = tmp_path / "src"
        src.mkdir()
        for i in range(15):
            (src / f"f{i}.py").write_text("x = 1\n")
        signals = detect_missing_annotations(tmp_path)
        assert len(signals) == 10


class TestGatherAll:
    def test_combines_sources(self, tmp_path: Path):
        signals = gather_all_learning_signals(tmp_path)
        assert isinstance(signals, list)
