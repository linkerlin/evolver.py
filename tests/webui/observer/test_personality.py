"""Tests for evolver.webui.observer.personality."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.webui.observer.personality import personality_data


class TestPersonalityData:
    def test_defaults_when_missing(self, tmp_path: Path):
        result = personality_data(memory_dir=tmp_path)
        assert result["dimensions"]["risk_tolerance"] == 0.5
        assert result["dimensions"]["exploration_rate"] == 0.3
        assert result["adaptations"] == []

    def test_reads_file(self, tmp_path: Path):
        data = {
            "risk_tolerance": 0.8,
            "exploration_rate": 0.6,
            "adaptations": [{"type": "speed_up"}],
            "updated_at": "2024-01-01",
        }
        (tmp_path / "personality.json").write_text(json.dumps(data))
        result = personality_data(memory_dir=tmp_path)
        assert result["dimensions"]["risk_tolerance"] == 0.8
        assert result["adaptations"] == [{"type": "speed_up"}]
        assert result["updated_at"] == "2024-01-01"
