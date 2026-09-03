"""Dogfood round-1 fixes (v1.107.0): runtime-state isolation + venv-bin
cascade fallback.

Round 1 on the real repo found: (a) daemon-churned memory/ files were
committed with the mutation and inflated blast radius (42 files for a
3-file change); (b) under a bare venv python the cascade skipped every
stage (ruff/mypy/pytest not on PATH) leaving unvalidated successes.
"""

from __future__ import annotations

import os
import types
from pathlib import Path

import pytest

from evolver.gep import solidify


class TestRuntimeStateIsolation:
    def test_runtime_paths_recognized(self) -> None:
        assert solidify._is_runtime_state("memory/evolution/memory_graph.jsonl")
        assert solidify._is_runtime_state(".evolver/gep/events.jsonl")
        assert solidify._is_runtime_state("evolver/.config/stake_state.json")
        assert not solidify._is_runtime_state("src/evolver/config.py")
        assert not solidify._is_runtime_state("tests/test_x.py")

    def test_blast_radius_excludes_runtime_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            solidify, "git_list_changed_files", lambda cwd: ["src/a.py", "memory/log.jsonl"]
        )
        monkeypatch.setattr(
            solidify,
            "git_list_untracked_files",
            lambda cwd: ["memory/evolution/newdir/", "tests/test_a.py"],
        )
        radius = solidify._compute_blast_radius()
        assert radius["files"] == 2  # only the source-tree files

    def test_commit_mutation_never_stages_runtime_state(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        staged: list[list[str]] = []
        monkeypatch.setattr(
            solidify,
            "git_list_changed_files",
            lambda cwd: ["src/a.py", "memory/churn.jsonl", ".evolver/gep/events.jsonl"],
        )
        monkeypatch.setattr(solidify, "_disposable_untracked", lambda cwd: [])
        monkeypatch.setattr(
            "evolver.gep.git_ops.run_cmd",
            lambda argv, cwd: staged.append(list(argv)) or "",
        )
        assert solidify._commit_mutation(tmp_path, "label") is True
        add_argv = staged[0]
        assert "src/a.py" in add_argv
        assert not any("memory/" in a or ".evolver/" in a for a in add_argv)


class TestCascadeVenvBinFallback:
    def test_falls_back_to_interpreter_bin(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        ruff = bin_dir / "ruff"
        ruff.write_text("#!/bin/sh\n", encoding="utf-8")
        ruff.chmod(0o755)

        monkeypatch.setattr(
            solidify,
            "FITNESS_CASCADE_COMMANDS",
            [{"command": ["ruff", "check", "src"]}],
        )
        monkeypatch.setattr(solidify.shutil, "which", lambda name: None)
        monkeypatch.setattr(
            solidify, "sys", types.SimpleNamespace(executable=str(bin_dir / "python"))
        )

        runnable = solidify.get_fitness_cascade_commands()
        assert len(runnable) == 1
        assert runnable[0]["command"][0] == str(ruff)

    def test_skips_when_nowhere_to_be_found(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            solidify,
            "FITNESS_CASCADE_COMMANDS",
            [{"command": ["definitely-missing-tool-xyz", "--version"]}],
        )
        monkeypatch.setattr(solidify.shutil, "which", lambda name: None)
        monkeypatch.setattr(
            solidify, "sys", types.SimpleNamespace(executable=str(tmp_path / "python"))
        )
        assert solidify.get_fitness_cascade_commands() == []

    def test_bare_venv_python_finds_real_tools(self) -> None:
        """The actual dogfood scenario: run under .venv/bin/python with a
        scrubbed PATH — the cascade must still resolve every stage."""
        import subprocess as sp

        code = (
            "import os, sys, json; os.environ['PATH'] = '/usr/bin:/bin'; "
            "from evolver.gep.solidify import get_fitness_cascade_commands; "
            "cmds = get_fitness_cascade_commands(); "
            "print(json.dumps([c['command'][0] for c in cmds]))"
        )
        proc = sp.run(
            [sys_exe(), "-c", code], capture_output=True, text=True, timeout=120, check=False
        )
        assert proc.returncode == 0, proc.stderr
        import json

        resolved = json.loads(proc.stdout)
        assert resolved and all(os.path.isabs(p) for p in resolved)


def sys_exe() -> str:
    import sys

    return sys.executable
