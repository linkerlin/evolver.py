"""Tests for evolver.webui.observer.safety."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.webui.observer.safety import safety_events


class TestSafetyEvents:
    def test_empty(self, tmp_path: Path):
        result = safety_events(memory_dir=tmp_path)
        assert result["total"] == 0
        assert result["severity_counts"] == {}

    def test_filters(self, tmp_path: Path):
        events = [
            {"type": "policy_violation", "severity": "high"},
            {"type": "interaction", "msg": "hello"},
            {"type": "secret_detected", "severity": "critical"},
            {"type": "rollback_triggered", "severity": "medium"},
        ]
        (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
        result = safety_events(memory_dir=tmp_path)
        assert result["total"] == 3
        assert result["severity_counts"]["high"] == 1
        assert result["severity_counts"]["critical"] == 1
        assert result["severity_counts"]["medium"] == 1

    def test_respects_limit(self, tmp_path: Path):
        events = [{"type": "policy_violation", "severity": "low"} for _ in range(20)]
        (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
        result = safety_events(limit=5, memory_dir=tmp_path)
        assert result["total"] == 5
