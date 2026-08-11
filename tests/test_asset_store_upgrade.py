"""Seed upgrade append semantics (v1.94.0 parity).

Behavioral port of the upgrade half of Node ``test/assetStore.test.js`` +
``assetStore.js`` ``ensureGenesSeeded`` v2: first run copies the seed
wholesale; later runs append only the bundled upgrade Gene family into stores
that look like an older bundled seed, under a file lock, without touching
user-owned or scratch stores.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep import asset_store
from evolver.gep.context_routing_gene import build_claude_context_gene_family

FAMILY_IDS = [g["id"] for g in build_claude_context_gene_family()]


@pytest.fixture
def iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Isolated seed + target with both paths patched."""
    seed_dir = tmp_path / "bundled"
    store_dir = tmp_path / "store"
    seed_dir.mkdir()
    store_dir.mkdir()
    monkeypatch.setattr(asset_store, "genes_seed_path", lambda: seed_dir / "genes.seed.json")
    monkeypatch.setattr(asset_store, "genes_path", lambda: store_dir / "genes.json")
    monkeypatch.setenv("GEP_ASSETS_DIR", str(store_dir))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    asset_store._LOCK_PATH = None  # type: ignore[attr-defined]
    return seed_dir / "genes.seed.json", store_dir / "genes.json"


def write_seed(seed_path: Path, genes: list[dict]) -> None:
    seed_path.write_text(
        json.dumps({"version": 1, "genes": genes}, ensure_ascii=False), encoding="utf-8"
    )


def marker_gene(gid: str) -> dict:
    return {"type": "Gene", "id": gid, "category": "optimize", "strategy": ["x"]}


def read_genes(target: Path) -> list[dict]:
    return json.loads(target.read_text(encoding="utf-8")).get("genes", [])


class TestSeedUpgrade:
    def test_first_run_copies_wholesale(self, iso: tuple[Path, Path]) -> None:
        seed_path, target = iso
        seed_genes = [marker_gene("gene_gep_repair_from_errors"), marker_gene("gene_tool_integrity")]
        write_seed(seed_path, seed_genes)
        asset_store.ensure_genes_seeded()
        assert [g["id"] for g in read_genes(target)] == [g["id"] for g in seed_genes]

    def test_old_bundled_seed_gets_family_appended(self, iso: tuple[Path, Path]) -> None:
        seed_path, target = iso
        old = [
            marker_gene("gene_gep_repair_from_errors"),
            marker_gene("gene_gep_optimize_prompt_and_assets"),
            {"type": "Gene", "id": "user_custom_gene", "category": "repair", "strategy": ["k"]},
        ]
        write_seed(seed_path, build_claude_context_gene_family())
        target.write_text(json.dumps({"version": 1, "genes": old}, ensure_ascii=False), encoding="utf-8")

        asset_store.ensure_genes_seeded()

        result = read_genes(target)
        ids = [g["id"] for g in result]
        assert "gene_gep_repair_from_errors" in ids and "user_custom_gene" in ids
        for fid in FAMILY_IDS:
            assert fid in ids, f"family gene {fid} must be appended"

    def test_marker_threshold_requires_two_hits(self, iso: tuple[Path, Path]) -> None:
        seed_path, target = iso
        write_seed(seed_path, build_claude_context_gene_family())
        # Only ONE marker id + hand-authored content: looks like a user store.
        target.write_text(
            json.dumps({"version": 1, "genes": [marker_gene("gene_gep_repair_from_errors")]}),
            encoding="utf-8",
        )
        asset_store.ensure_genes_seeded()
        assert all(g["id"] not in FAMILY_IDS for g in read_genes(target))

    def test_empty_scratch_store_untouched(self, iso: tuple[Path, Path]) -> None:
        seed_path, target = iso
        write_seed(seed_path, build_claude_context_gene_family())
        target.write_text(json.dumps({"version": 1, "genes": []}), encoding="utf-8")
        asset_store.ensure_genes_seeded()
        assert read_genes(target) == []

    def test_idempotent_no_duplicates(self, iso: tuple[Path, Path]) -> None:
        seed_path, target = iso
        old = [marker_gene("gene_gep_repair_from_errors"), marker_gene("gene_tool_integrity")]
        write_seed(seed_path, build_claude_context_gene_family())
        target.write_text(json.dumps({"version": 1, "genes": old}, ensure_ascii=False), encoding="utf-8")
        asset_store.ensure_genes_seeded()
        asset_store.ensure_genes_seeded()
        ids = [g["id"] for g in read_genes(target)]
        assert len(ids) == len(set(ids))
        assert all(fid in ids for fid in FAMILY_IDS)

    def test_select_only_missing_family_genes(self, iso: tuple[Path, Path]) -> None:
        seed_path, target = iso
        write_seed(seed_path, build_claude_context_gene_family())
        target.write_text(
            json.dumps({"version": 1, "genes": [marker_gene("gene_gep_repair_from_errors")]}),
            encoding="utf-8",
        )
        with asset_store.with_file_lock(target_path=target):
            current = asset_store.read_json_if_exists(target) or {"genes": []}
            existing = list(current.get("genes", []))
            existing_ids = {g["id"] for g in existing}
            missing = asset_store.select_bundled_upgrade_genes(
                build_claude_context_gene_family(), existing_ids
            )
            assert [g["id"] for g in missing] == FAMILY_IDS
            second = asset_store.select_bundled_upgrade_genes(
                build_claude_context_gene_family(), existing_ids | set(FAMILY_IDS)
            )
            assert second == []
