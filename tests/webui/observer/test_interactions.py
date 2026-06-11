"""Tests for evolver.webui.observer.interactions."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.webui.observer.interactions import format_interactions


class TestFormatInteractions:
    def test_empty(self, tmp_path: Path):
        result = format_interactions(memory_dir=tmp_path)
        assert result == []

    def test_filters_and_redacts(self, tmp_path: Path):
        events = [
            {"type": "interaction", "message": "Hello", "timestamp": 1.0},
            {"type": "session", "summary": "Done", "timestamp": 2.0},
            {"type": "pipeline_phase", "phase": "enrich", "timestamp": 3.0},
            {"type": "interaction", "message": "Bearer sk-12345678901234567890", "timestamp": 4.0},
        ]
        (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
        result = format_interactions(limit=10, memory_dir=tmp_path)
        assert len(result) == 3  # pipeline_phase filtered out
        # Most recent first
        assert result[0]["message"] == "Bearer <REDACTED>"
        assert "sk-1234567890" not in result[0]["message"]

    def test_respects_limit(self, tmp_path: Path):
        events = [
            {"type": "interaction", "message": str(i), "timestamp": float(i)} for i in range(20)
        ]
        (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
        result = format_interactions(limit=5, memory_dir=tmp_path)
        assert len(result) == 5
