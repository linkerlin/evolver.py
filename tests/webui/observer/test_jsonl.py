"""Tests for evolver.webui.observer.jsonl."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.webui.observer.jsonl import stream_jsonl


class TestStreamJsonl:
    def test_empty_file(self, tmp_path: Path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        assert list(stream_jsonl(path)) == []

    def test_missing_file(self, tmp_path: Path):
        path = tmp_path / "missing.jsonl"
        assert list(stream_jsonl(path)) == []

    def test_basic(self, tmp_path: Path):
        path = tmp_path / "events.jsonl"
        lines = [{"id": 1}, {"id": 2}]
        path.write_text("\n".join(json.dumps(l) for l in lines))
        result = list(stream_jsonl(path))
        assert len(result) == 2
        assert result[0]["id"] == 1

    def test_limit(self, tmp_path: Path):
        path = tmp_path / "events.jsonl"
        lines = [{"id": i} for i in range(10)]
        path.write_text("\n".join(json.dumps(l) for l in lines))
        result = list(stream_jsonl(path, limit=3))
        assert len(result) == 3

    def test_since_filter(self, tmp_path: Path):
        path = tmp_path / "events.jsonl"
        lines = [
            {"id": 1, "timestamp": 100.0},
            {"id": 2, "timestamp": 200.0},
            {"id": 3, "timestamp": 300.0},
        ]
        path.write_text("\n".join(json.dumps(l) for l in lines))
        result = list(stream_jsonl(path, since=150.0))
        assert len(result) == 2
        assert result[0]["id"] == 2

    def test_malformed_line_skipped(self, tmp_path: Path):
        path = tmp_path / "events.jsonl"
        path.write_text('{"id":1}\nnot json\n{"id":2}')
        result = list(stream_jsonl(path))
        assert len(result) == 2
