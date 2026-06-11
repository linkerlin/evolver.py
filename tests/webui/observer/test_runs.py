"""Tests for evolver.webui.observer.runs."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.webui.observer.runs import runs_history


class TestRunsHistory:
    def test_empty(self, tmp_path: Path):
        result = runs_history(memory_dir=tmp_path)
        assert result["total_cycles"] == 0
        assert result["successes"] == 0
        assert result["success_rate"] == 0.0

    def test_counts(self, tmp_path: Path):
        events = [
            {"type": "cycle_end", "outcome": "success", "timestamp": 1.0},
            {"type": "cycle_end", "outcome": "success", "timestamp": 2.0},
            {"type": "cycle_end", "outcome": "failure", "timestamp": 3.0},
        ]
        (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
        result = runs_history(memory_dir=tmp_path)
        assert result["total_cycles"] == 3
        assert result["successes"] == 2
        assert result["failures"] == 1
        assert result["success_rate"] == round(2 / 3, 3)

    def test_recent_limit(self, tmp_path: Path):
        events = [
            {"type": "cycle_end", "outcome": "success", "timestamp": float(i)} for i in range(10)
        ]
        (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
        result = runs_history(limit=3, memory_dir=tmp_path)
        assert len(result["recent"]) == 3
