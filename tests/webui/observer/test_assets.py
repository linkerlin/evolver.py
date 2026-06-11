"""Tests for evolver.webui.observer.assets."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.webui.observer.assets import serialize_assets


class TestSerializeAssets:
    def test_empty(self, tmp_path: Path):
        result = serialize_assets(memory_dir=tmp_path)
        assert result["total"] == 0
        assert result["items"] == []
        assert result["page"] == 1

    def test_with_genes(self, tmp_path: Path):
        genes = {"genes": [{"id": "g1", "summary": "Gene one"}]}
        (tmp_path / "genes.json").write_text(json.dumps(genes))
        result = serialize_assets(memory_dir=tmp_path)
        assert result["total"] == 1
        assert result["items"][0]["id"] == "g1"

    def test_type_filter(self, tmp_path: Path):
        genes = {"genes": [{"id": "g1"}]}
        capsules = {"capsules": [{"id": "c1"}]}
        (tmp_path / "genes.json").write_text(json.dumps(genes))
        (tmp_path / "capsules.json").write_text(json.dumps(capsules))

        result = serialize_assets(memory_dir=tmp_path, type_filter="gene")
        assert result["total"] == 1
        assert result["items"][0]["type"] == "gene"

    def test_query_filter(self, tmp_path: Path):
        genes = {"genes": [{"id": "g1", "summary": "alpha"}, {"id": "g2", "summary": "beta"}]}
        (tmp_path / "genes.json").write_text(json.dumps(genes))
        result = serialize_assets(memory_dir=tmp_path, query="beta")
        assert result["total"] == 1
        assert result["items"][0]["id"] == "g2"

    def test_pagination(self, tmp_path: Path):
        genes = {"genes": [{"id": f"g{i}"} for i in range(10)]}
        (tmp_path / "genes.json").write_text(json.dumps(genes))
        result = serialize_assets(memory_dir=tmp_path, page=1, limit=5)
        assert len(result["items"]) == 5
        result2 = serialize_assets(memory_dir=tmp_path, page=2, limit=5)
        assert len(result2["items"]) == 5
