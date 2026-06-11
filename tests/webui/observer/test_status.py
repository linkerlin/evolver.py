"""Tests for evolver.webui.observer.status."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.webui.observer.status import system_status


class TestSystemStatus:
    def test_basic(self, tmp_path: Path):
        result = system_status(memory_dir=tmp_path)
        assert "timestamp" in result
        assert "components" in result
        assert "overall" in result
        # No events file → exists False
        assert result["components"]["events"]["exists"] is False

    def test_with_events(self, tmp_path: Path):
        (tmp_path / "events.jsonl").write_text("{}")
        result = system_status(memory_dir=tmp_path)
        assert result["components"]["events"]["exists"] is True
        assert result["components"]["events"]["size_bytes"] >= 0

    def test_with_genes_capsules(self, tmp_path: Path):
        (tmp_path / "genes.json").write_text(json.dumps({"genes": [{"id": "g1"}]}))
        (tmp_path / "capsules.json").write_text(json.dumps({"capsules": [{"id": "c1"}]}))
        result = system_status(memory_dir=tmp_path)
        assert result["components"]["genes"]["count"] == 1
        assert result["components"]["capsules"]["count"] == 1

    def test_overall_healthy(self, tmp_path: Path):
        result = system_status(memory_dir=tmp_path)
        assert result["overall"] in ("healthy", "warning", "critical")
