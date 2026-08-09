"""Tests for evolver.gep.candidate_isolation (Sprint A2)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from evolver.gep.candidate_isolation import (
    candidate_import_context,
    is_python_surface_change,
    load_candidate_module,
)


def _write_module(dir_path: Path, name: str, value: str) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    p = dir_path / f"{name}.py"
    p.write_text(f"VALUE = {value!r}\n", encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def _clean_probe_modules() -> None:
    """Evict the shared 'probe' test module after each test.

    Without this, a bare ``import probe`` in one test pollutes sys.modules
    for the next, and context-exit restore of a module that does not exist
    under the next test's base dir breaks it.
    """
    yield
    sys.modules.pop("probe", None)


class TestCandidateImportContext:
    def test_loads_candidate_version(self, tmp_path: Path) -> None:
        mod_a = _write_module(tmp_path / "base", "probe", "base")
        mod_b = _write_module(tmp_path / "cand", "probe", "cand")
        # prime the base version
        with candidate_import_context(tmp_path / "base", ["probe"]):
            import probe

            assert probe.VALUE == "base"
        # candidate version wins inside the context
        with candidate_import_context(tmp_path / "cand", ["probe"]):
            import probe

            assert probe.VALUE == "cand"

    def test_restores_module_after_exit(self, tmp_path: Path) -> None:
        _write_module(tmp_path / "base", "probe", "base")
        _write_module(tmp_path / "cand", "probe", "cand")
        with candidate_import_context(tmp_path / "cand", ["probe"]):
            import probe

            assert probe.VALUE == "cand"
        # outside the context: candidate module evicted, base restored
        with candidate_import_context(tmp_path / "base", ["probe"]):
            import probe

            assert probe.VALUE == "base"

    def test_restores_sys_path(self, tmp_path: Path) -> None:
        _write_module(tmp_path / "cand", "probe", "x")
        old_path = list(sys.path)
        with candidate_import_context(tmp_path / "cand", ["probe"]):
            pass
        assert sys.path == old_path


class TestLoadCandidateModule:
    def test_returns_candidate_value(self, tmp_path: Path) -> None:
        _write_module(tmp_path / "base", "probe", "base")
        _write_module(tmp_path / "cand", "probe", "cand")
        module = load_candidate_module(tmp_path / "cand", "probe")
        assert module.VALUE == "cand"

    def test_does_not_leak_sys_path(self, tmp_path: Path) -> None:
        _write_module(tmp_path / "cand", "probe", "x")
        old_path = list(sys.path)
        load_candidate_module(tmp_path / "cand", "probe")
        assert sys.path == old_path


class TestIsPythonSurfaceChange:
    def test_py_change_true(self) -> None:
        assert is_python_surface_change(["src/a.py"]) is True

    def test_non_py_false(self) -> None:
        assert is_python_surface_change(["docs/x.md", "config.json"]) is False

    def test_mixed_true(self) -> None:
        assert is_python_surface_change(["docs/x.md", "src/a.py"]) is True

    def test_empty_false(self) -> None:
        assert is_python_surface_change([]) is False
