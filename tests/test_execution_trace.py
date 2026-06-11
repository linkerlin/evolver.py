"""Tests for evolver.gep.execution_trace."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from evolver.gep.execution_trace import (
    classify_blast_level,
    desensitize_file_path,
    extract_error_signature,
    get_trace_level,
    infer_tool_chain,
    build_execution_trace,
)


class TestGetTraceLevel:
    def test_default(self, monkeypatch):
        monkeypatch.delenv("EVOLVER_TRACE_LEVEL", raising=False)
        assert get_trace_level() == "minimal"

    def test_env(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_TRACE_LEVEL", "full")
        assert get_trace_level() == "full"

    def test_invalid(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_TRACE_LEVEL", "weird")
        assert get_trace_level() == "minimal"


class TestDesensitizeFilePath:
    def test_home(self):
        home = str(Path.home())
        p = os.path.join(home, "secret.txt")
        assert desensitize_file_path(p).startswith("~")


class TestExtractErrorSignature:
    def test_found(self):
        sig = extract_error_signature("Traceback:\nValueError: bad\n")
        assert sig == "ValueError: bad"

    def test_not_found(self):
        assert extract_error_signature("no issues here") is None

    def test_empty(self):
        assert extract_error_signature("") is None


class TestInferToolChain:
    def test_python(self):
        assert infer_tool_chain("python foo.py") == "python"

    def test_pytest(self):
        assert infer_tool_chain("pytest tests/") == "pytest"

    def test_git(self):
        assert infer_tool_chain("git status") == "git"

    def test_shell(self):
        assert infer_tool_chain("echo hi") == "shell"


class TestClassifyBlastLevel:
    def test_tiny(self):
        assert classify_blast_level(1, 20) == "tiny"

    def test_small(self):
        assert classify_blast_level(3, 100) == "small"

    def test_medium(self):
        assert classify_blast_level(10, 500) == "medium"

    def test_large(self):
        assert classify_blast_level(100, 1000) == "large"


class TestBuildExecutionTrace:
    def test_none(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_TRACE_LEVEL", "none")
        assert build_execution_trace(["cmd"], ["out"]) == []

    def test_minimal(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_TRACE_LEVEL", "minimal")
        trace = build_execution_trace(["pytest"], ["passed"])
        assert len(trace) == 1
        assert trace[0]["tool"] == "pytest"
        assert "output_preview" not in trace[0]

    def test_full(self, monkeypatch):
        monkeypatch.setenv("EVOLVER_TRACE_LEVEL", "full")
        trace = build_execution_trace(["pytest"], ["ERROR: failed\n"])
        assert len(trace) == 1
        assert "output_preview" in trace[0]
        assert "error_signature" in trace[0]
