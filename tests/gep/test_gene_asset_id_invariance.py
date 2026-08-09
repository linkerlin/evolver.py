"""C-3 asset_id invariance: Gene schema extension must not break hashing.

Adding optional fields (mechanism_family / target_hook) must not invalidate
existing genes' content hashes — hashes are computed on raw on-disk dicts
(asset_store keeps on-disk shape, PR #25). This test pins that invariant.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep.asset_store import load_genes, upsert_gene
from evolver.gep.content_hash import compute_asset_id, verify_asset_id
from evolver.gep.schemas.gene import Gene


def _seed_gene_with_new_fields() -> dict:
    """A gene as a NEW constrained gene would be persisted (fields included)."""
    gene = {
        "type": "Gene",
        "id": "g_constrained",
        "category": "repair",
        "signals_match": ["log_error"],
        "strategy": ["step 1"],
        "validation": [],
        "mechanism_family": "prompt_instruction",
        "target_hook": "build_gep_prompt",
    }
    gene["asset_id"] = compute_asset_id(gene)
    return gene


class TestAssetIdInvariance:
    def test_hash_computed_on_raw_dict_with_new_fields(self) -> None:
        gene = _seed_gene_with_new_fields()
        assert verify_asset_id(gene, gene["asset_id"]) is True

    def test_model_validate_does_not_break_stored_hash(self) -> None:
        # Loading through Pydantic is fine as long as we hash the RAW dict.
        gene = _seed_gene_with_new_fields()
        parsed = Gene.model_validate(gene)
        raw = gene  # hash the on-disk dict, NOT parsed.model_dump()
        assert verify_asset_id(raw, parsed.asset_id or "") is True

    def test_old_style_gene_hash_unaffected(self) -> None:
        # a gene WITHOUT the new fields keeps its original hash
        gene = {
            "type": "Gene",
            "id": "g_old",
            "category": "innovate",
            "signals_match": [],
            "strategy": [],
            "validation": [],
        }
        gene["asset_id"] = compute_asset_id(gene)
        assert verify_asset_id(gene, gene["asset_id"]) is True
        # model_dump round-trip WOULD change the payload — that is the
        # forbidden pattern (C-3). We assert it here to document the trap.
        dumped = Gene.model_validate(gene).model_dump(exclude={"asset_id"})
        assert compute_asset_id(dumped) != gene["asset_id"]


class TestLoadGenesWithConstrainedField:
    def test_seed_genes_still_load_with_new_fields_schema(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "evolver.gep.asset_store.get_gep_assets_dir",
            lambda: tmp_path / "gep",
        )
        # seed a constrained gene into the store, then load everything
        upsert_gene(_seed_gene_with_new_fields())
        genes = load_genes(seed=False)
        ids = {g["id"] for g in genes}
        assert "g_constrained" in ids
        # loaded genes still verify their asset ids (raw-dict verification)
        for gene in genes:
            if gene.get("asset_id"):
                assert verify_asset_id(gene, gene["asset_id"]) is True
