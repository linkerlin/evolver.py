"""Tests for evolver.gep.asset_store — equivalent to evolver/test/assetStore.test.js."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep import asset_store
from evolver.gep.content_hash import compute_asset_id


def test_read_json_if_exists_missing() -> None:
    assert asset_store.read_json_if_exists(Path("/does/not/exist")) is None


def test_atomic_write_json_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    data = {"version": 1, "genes": [{"id": "g1"}]}
    asset_store.atomic_write_json(path, data)
    assert asset_store.read_json_if_exists(path) == data


def test_append_jsonl_and_read(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    asset_store.append_jsonl(path, {"id": "e1"})
    asset_store.append_jsonl(path, {"id": "e2"})
    rows = asset_store.read_jsonl_all(path)
    assert [r["id"] for r in rows] == ["e1", "e2"]


def test_load_genes_with_overlay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path))
    asset_store.atomic_write_json(tmp_path / "genes.json", {"version": 1, "genes": [{"id": "g1", "category": "repair"}]})
    asset_store.append_jsonl(tmp_path / "genes.jsonl", {"id": "g1", "category": "innovate"})
    genes = asset_store.load_genes()
    assert len(genes) == 1
    assert genes[0]["category"] == "innovate"


def test_upsert_gene_adds_asset_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path))
    gene = {"type": "Gene", "id": "g2", "category": "repair", "signals_match": ["error"]}
    asset_store.upsert_gene(gene)
    genes = asset_store.load_genes()
    assert any(g["id"] == "g2" and "asset_id" in g for g in genes)


def test_load_genes_skips_hash_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path))
    gene = {"type": "Gene", "id": "g3", "category": "repair"}
    gene["asset_id"] = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
    asset_store.append_jsonl(tmp_path / "genes.jsonl", gene)
    genes = asset_store.load_genes()
    assert all(g["id"] != "g3" for g in genes)


def test_load_genes_keeps_valid_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path))
    gene = {"type": "Gene", "id": "g4", "category": "repair"}
    gene["asset_id"] = compute_asset_id(gene)
    asset_store.append_jsonl(tmp_path / "genes.jsonl", gene)
    genes = asset_store.load_genes()
    assert any(g["id"] == "g4" for g in genes)


def test_append_capsule_adds_asset_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path))
    cap = {"type": "Capsule", "id": "c1", "trigger": ["error"]}
    asset_store.append_capsule(cap)
    capsules = asset_store.load_capsules()
    assert any(c["id"] == "c1" and "asset_id" in c for c in capsules)
