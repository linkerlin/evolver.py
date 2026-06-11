"""Tests for evolver.webui.observer.pipeline_events."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.webui.observer.pipeline_events import pipeline_timeline


class TestPipelineTimeline:
    def test_empty(self, tmp_path: Path):
        result = pipeline_timeline(memory_dir=tmp_path)
        assert result == []

    def test_filters_pipeline_events(self, tmp_path: Path):
        events = [
            {"type": "pipeline_start", "phase": "collect"},
            {"type": "interaction", "msg": "hello"},
            {"type": "pipeline_phase", "phase": "enrich"},
            {"type": "cycle_end", "outcome": "success"},
        ]
        (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
        result = pipeline_timeline(memory_dir=tmp_path)
        assert len(result) == 3
        assert all(
            e["type"]
            in ("pipeline_start", "pipeline_phase", "pipeline_end", "cycle_start", "cycle_end")
            for e in result
        )

    def test_respects_limit(self, tmp_path: Path):
        events = [{"type": "pipeline_phase", "i": i} for i in range(20)]
        (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
        result = pipeline_timeline(limit=5, memory_dir=tmp_path)
        assert len(result) == 5
