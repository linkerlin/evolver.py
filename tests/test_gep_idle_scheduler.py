"""Tests for evolver.gep.idle_scheduler — override + build activity + FS fallback."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

import evolver.gep.paths as paths_mod
from evolver.gep import idle_scheduler

SI = idle_scheduler.EvolutionIntensity


class TestIntensityOverride:
    def test_override_deep(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_IDLE_OVERRIDE", "deep")
        assert idle_scheduler.get_intensity() == SI.deep

    def test_override_signal_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_IDLE_OVERRIDE", "signal_only")
        assert idle_scheduler.get_intensity() == SI.signal_only

    def test_override_invalid_falls_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_IDLE_OVERRIDE", "nonsense")
        monkeypatch.setattr(idle_scheduler, "_detect_build_activity", lambda: False)
        monkeypatch.setattr(idle_scheduler, "_idle_time", lambda: 0.0)
        assert idle_scheduler.get_intensity() == SI.signal_only


class TestBuildActivityDetection:
    def test_recent_file_means_active(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "recent.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(paths_mod, "get_workspace_root", lambda: tmp_path)
        assert idle_scheduler._detect_build_activity() is True

    def test_no_recent_file_means_inactive(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        old_file = memory_dir / "old.json"
        old_file.write_text("{}", encoding="utf-8")
        old_time = time.time() - 3600
        os.utime(old_file, (old_time, old_time))
        monkeypatch.setattr(paths_mod, "get_workspace_root", lambda: tmp_path)
        assert idle_scheduler._detect_build_activity() is False


class TestFsIdleFallback:
    def test_returns_zero_for_empty_dir(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(paths_mod, "get_memory_dir", lambda: tmp_path / "memory")
        result = idle_scheduler._fs_idle_fallback()
        assert result == 0.0

    def test_returns_idle_for_old_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        old_file = memory_dir / "old.json"
        old_file.write_text("{}", encoding="utf-8")
        old_time = time.time() - 600  # 10 min ago
        os.utime(old_file, (old_time, old_time))
        monkeypatch.setattr(paths_mod, "get_memory_dir", lambda: memory_dir)
        result = idle_scheduler._fs_idle_fallback()
        assert result >= 500  # roughly 10 min


class TestIntensityForDuration:
    def test_signal_only(self) -> None:
        assert idle_scheduler.intensity_for_duration(0) == SI.signal_only
        assert idle_scheduler.intensity_for_duration(30) == SI.signal_only

    def test_light(self) -> None:
        assert idle_scheduler.intensity_for_duration(60) == SI.light
        assert idle_scheduler.intensity_for_duration(120) == SI.light

    def test_normal(self) -> None:
        assert idle_scheduler.intensity_for_duration(300) == SI.normal

    def test_deep(self) -> None:
        assert idle_scheduler.intensity_for_duration(900) == SI.deep
        assert idle_scheduler.intensity_for_duration(9999) == SI.deep
