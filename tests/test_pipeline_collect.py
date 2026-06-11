"""Tests for evolver.evolve.pipeline.collect."""

from __future__ import annotations

from evolver.evolve.pipeline.collect import (
    _read_file_snippet,
    check_system_health,
    format_cursor_transcript,
    get_mutation_directive,
)


class TestReadFileSnippet:
    def test_exists(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_text("hello")
        assert _read_file_snippet(p) == "hello"

    def test_missing(self, tmp_path):
        assert "MISSING" in _read_file_snippet(tmp_path / "no.txt")

    def test_truncated(self, tmp_path):
        p = tmp_path / "b.txt"
        p.write_text("x" * 10_000)
        out = _read_file_snippet(p, max_chars=100)
        assert out.endswith("...[truncated]\n")


class TestGetMutationDirective:
    def test_repair_unstable(self):
        log = "error\nerror\nerror\nerror"
        out = get_mutation_directive(log)
        assert "repair" in out
        assert "unstable" in out

    def test_repair_stable(self):
        log = "one error"
        out = get_mutation_directive(log)
        assert "repair" in out
        assert "stable" in out

    def test_optimize(self):
        log = "TODO fix this"
        out = get_mutation_directive(log)
        assert "optimize" in out

    def test_innovate(self):
        out = get_mutation_directive("clean")
        assert "innovate" in out


class TestCheckSystemHealth:
    def test_contains_platform(self):
        out = check_system_health()
        assert "python_version" in out
        assert "platform" in out


class TestFormatCursorTranscript:
    def test_filters_sse(self):
        raw = "data: hello\nevent: start\ndata: world"
        out = format_cursor_transcript(raw)
        assert "data: hello" not in out
        assert "event: start" in out
