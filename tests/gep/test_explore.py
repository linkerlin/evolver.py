"""Tests for evolver.gep.explore."""

import tempfile
from pathlib import Path

import pytest

from evolver.gep.explore import (
    ExplorationTask,
    explore_workspace,
    top_exploration_signals,
)


class TestExploreWorkspace:
    def test_finds_todo(self, tmp_path):
        py_file = tmp_path / "mod.py"
        py_file.write_text("# TODO: fix this\ndef foo(): pass\n", encoding="utf-8")
        tasks = explore_workspace(root=tmp_path, max_tasks=20)
        assert any(t.task_type == "todo" and "fix this" in t.description for t in tasks)

    def test_finds_missing_docstring(self, tmp_path):
        py_file = tmp_path / "mod.py"
        py_file.write_text("def foo():\n    pass\n", encoding="utf-8")
        tasks = explore_workspace(root=tmp_path, max_tasks=20)
        assert any(t.task_type == "missing_docstring" and t.symbol == "foo" for t in tasks)

    def test_finds_missing_type_hint(self, tmp_path):
        py_file = tmp_path / "mod.py"
        py_file.write_text("def foo(x):\n    pass\n", encoding="utf-8")
        tasks = explore_workspace(root=tmp_path, max_tasks=20)
        assert any(t.task_type == "missing_type_hint" and t.symbol == "foo" for t in tasks)

    def test_skips_venv(self, tmp_path):
        venv = tmp_path / ".venv" / "lib.py"
        venv.parent.mkdir(parents=True)
        venv.write_text("# TODO: hidden\n", encoding="utf-8")
        tasks = explore_workspace(root=tmp_path, max_tasks=20)
        assert not any("hidden" in t.description for t in tasks)

    def test_limits_max_tasks(self, tmp_path):
        for i in range(10):
            (tmp_path / f"mod{i}.py").write_text("def foo(): pass\n", encoding="utf-8")
        tasks = explore_workspace(root=tmp_path, max_tasks=5)
        assert len(tasks) <= 5


class TestSignals:
    def test_returns_dicts(self, tmp_path):
        (tmp_path / "mod.py").write_text("# TODO: test\n", encoding="utf-8")
        signals = top_exploration_signals(root=tmp_path, max_tasks=10)
        assert all(isinstance(s, dict) for s in signals)
        assert any(s["type"] == "explore" for s in signals)
