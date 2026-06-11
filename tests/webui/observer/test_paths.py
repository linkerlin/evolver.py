"""Tests for evolver.webui.observer.paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.webui.observer.paths import sanitize_path


class TestSanitizePath:
    def test_relative_to_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        f = tmp_path / "src" / "main.py"
        f.parent.mkdir(parents=True)
        f.write_text("x")
        assert sanitize_path(f) == "src/main.py"

    def test_under_home(self, monkeypatch: pytest.MonkeyPatch):
        home = Path.home()
        f = home / "doc" / "file.txt"
        # Do not actually create the file; function works on string paths
        result = sanitize_path(str(f))
        assert result.startswith("~/")
        assert "doc/file.txt" in result

    def test_outside_home(self, tmp_path: Path):
        # Use a path under tmp_path which is usually outside home
        f = tmp_path / "deep" / "file.txt"
        result = sanitize_path(str(f))
        # Falls back to filename only
        assert result == "file.txt"

    def test_string_input(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        f = tmp_path / "a.py"
        f.write_text("x")
        assert sanitize_path(str(f)) == "a.py"
