"""Tests for evolver.gep.asset_store — ports Node assetStore + filelock contracts."""

from __future__ import annotations

import concurrent.futures
import time
from pathlib import Path

import pytest

from evolver.gep import asset_store
from evolver.gep.content_hash import compute_asset_id, verify_asset_id


@pytest.fixture
def assets_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "assets" / "gep"
    d.mkdir(parents=True)
    monkeypatch.setenv("GEP_ASSETS_DIR", str(d))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("EVOLVER_SESSION_SCOPE", raising=False)
    # Reset module lock path cache so it re-resolves under GEP_ASSETS_DIR.
    asset_store._LOCK_PATH = None  # type: ignore[attr-defined]
    return d


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


def test_read_recent_candidates_missing(assets_dir: Path) -> None:
    assert asset_store.read_recent_candidates() == []


def test_read_recent_candidates_empty_file(assets_dir: Path) -> None:
    (assets_dir / "candidates.jsonl").write_text("", encoding="utf-8")
    assert asset_store.read_recent_candidates() == []


def test_read_recent_candidates_parses_jsonl(assets_dir: Path) -> None:
    asset_store.append_candidate_jsonl({"type": "Candidate", "id": "c1", "score": 0.8})
    asset_store.append_candidate_jsonl({"type": "Candidate", "id": "c2", "score": 0.9})
    result = asset_store.read_recent_candidates(10)
    assert [r["id"] for r in result] == ["c1", "c2"]


def test_read_recent_candidates_respects_limit(assets_dir: Path) -> None:
    for i in range(10):
        asset_store.append_candidate_jsonl({"type": "Candidate", "id": f"c{i}"})
    result = asset_store.read_recent_candidates(3)
    assert [r["id"] for r in result] == ["c7", "c8", "c9"]


def test_read_recent_candidates_skips_malformed(assets_dir: Path) -> None:
    (assets_dir / "candidates.jsonl").write_text(
        '{"id":"c1"}\n{BROKEN\n{"id":"c2"}\n', encoding="utf-8"
    )
    result = asset_store.read_recent_candidates(10)
    assert [r["id"] for r in result] == ["c1", "c2"]


def test_read_recent_candidates_large_file_tail_only(assets_dir: Path) -> None:
    path = assets_dir / "candidates.jsonl"
    padding = '{"type":"pad","data":"' + ("x" * 500) + '"}\n'
    pad_count = (1024 * 1024 + 100) // len(padding) + 1
    with path.open("w", encoding="utf-8") as handle:
        for _ in range(pad_count):
            handle.write(padding)
        handle.write('{"type":"tail","id":"last1"}\n')
        handle.write('{"type":"tail","id":"last2"}\n')
    assert path.stat().st_size > 1024 * 1024
    result = asset_store.read_recent_candidates(2)
    assert [r["id"] for r in result] == ["last1", "last2"]


def test_append_candidate_roundtrip(assets_dir: Path) -> None:
    asset_store.append_candidate_jsonl({"type": "Candidate", "id": "rt1"})
    asset_store.append_candidate_jsonl({"type": "Candidate", "id": "rt2"})
    result = asset_store.read_recent_candidates(10)
    assert [r["id"] for r in result] == ["rt1", "rt2"]


def test_external_candidates_default_limit(assets_dir: Path) -> None:
    for i in range(60):
        asset_store.append_external_candidate_jsonl({"id": f"e{i}"})
    # default limit 50
    assert len(asset_store.read_recent_external_candidates()) == 50


# ---------------------------------------------------------------------------
# Genes / capsules
# ---------------------------------------------------------------------------


def test_load_genes_with_overlay(assets_dir: Path) -> None:
    asset_store.atomic_write_json(
        assets_dir / "genes.json", {"version": 1, "genes": [{"id": "g1", "category": "repair"}]}
    )
    asset_store.append_jsonl(assets_dir / "genes.jsonl", {"id": "g1", "category": "innovate"})
    genes = asset_store.load_genes()
    assert len(genes) == 1
    assert genes[0]["category"] == "innovate"


def test_upsert_gene_adds_asset_id(assets_dir: Path) -> None:
    gene = {"type": "Gene", "id": "g2", "category": "repair", "signals_match": ["error"]}
    asset_store.upsert_gene(gene)
    genes = asset_store.load_genes()
    assert any(g["id"] == "g2" and "asset_id" in g for g in genes)


def test_load_genes_skips_hash_mismatch(assets_dir: Path) -> None:
    gene = {"type": "Gene", "id": "g3", "category": "repair"}
    gene["asset_id"] = "sha256:" + "0" * 64
    asset_store.append_jsonl(assets_dir / "genes.jsonl", gene)
    genes = asset_store.load_genes()
    assert all(g["id"] != "g3" for g in genes)


def test_load_genes_keeps_valid_hash(assets_dir: Path) -> None:
    gene = {"type": "Gene", "id": "g4", "category": "repair"}
    gene["asset_id"] = compute_asset_id(gene)
    asset_store.append_jsonl(assets_dir / "genes.jsonl", gene)
    genes = asset_store.load_genes()
    assert any(g["id"] == "g4" for g in genes)


def test_append_capsule_adds_asset_id(assets_dir: Path) -> None:
    cap = {"type": "Capsule", "id": "c1", "trigger": ["error"]}
    asset_store.append_capsule(cap)
    capsules = asset_store.load_capsules()
    assert any(c["id"] == "c1" and "asset_id" in c for c in capsules)


def test_load_genes_preserves_on_disk_shape(assets_dir: Path) -> None:
    """Must not synthesize defaults that would invalidate asset_id (PR #25)."""
    legacy = {
        "type": "Gene",
        "id": "gene_legacy",
        "category": "repair",
        "signals_match": ["error"],
        "strategy": ["fix it"],
    }
    legacy["asset_id"] = compute_asset_id(legacy)
    asset_store.atomic_write_json(assets_dir / "genes.json", {"version": 1, "genes": [legacy]})
    loaded = next(g for g in asset_store.load_genes() if g["id"] == "gene_legacy")
    assert verify_asset_id(loaded, loaded["asset_id"])
    for field in (
        "epigenetic_marks",
        "learning_history",
        "anti_patterns",
        "schema_version",
        "summary",
    ):
        assert field not in loaded


def test_load_genes_seed_false_no_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assets = tmp_path / "empty" / "gep"
    monkeypatch.setenv("GEP_ASSETS_DIR", str(assets))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    asset_store._LOCK_PATH = None  # type: ignore[attr-defined]
    assert not assets.exists()
    genes = asset_store.load_genes(seed=False)
    # In-memory seed may still return bundled genes without creating dirs.
    assert isinstance(genes, list)
    assert not assets.exists() or not (assets / "genes.json").exists()


def test_load_genes_read_only_does_not_create_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets = tmp_path / "missing" / "gep"
    monkeypatch.setenv("GEP_ASSETS_DIR", str(assets))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    asset_store._LOCK_PATH = None  # type: ignore[attr-defined]
    genes = asset_store.load_genes_read_only()
    capsules = asset_store.load_capsules_read_only()
    assert isinstance(genes, list)
    assert capsules == []
    assert not assets.exists()


def test_ensure_genes_seeded_copies_once(assets_dir: Path) -> None:
    target = assets_dir / "genes.json"
    if target.exists():
        target.unlink()
    # Point seed to a local file we control.
    seed = assets_dir / "genes.seed.json"
    seed.write_text(
        '{"version":1,"genes":[{"type":"Gene","id":"seed_g1","category":"repair"}]}',
        encoding="utf-8",
    )
    # Monkeypatch seed path via bundled dir is hard; call ensure after writing
    # by temporarily replacing genes_seed_path.
    original = asset_store.genes_seed_path
    asset_store.genes_seed_path = lambda: seed  # type: ignore[assignment]
    try:
        assert not target.exists()
        asset_store.ensure_genes_seeded()
        assert target.exists()
        first = target.read_text(encoding="utf-8")
        # Second call must not overwrite user store.
        target.write_text('{"version":1,"genes":[{"id":"user"}]}', encoding="utf-8")
        asset_store.ensure_genes_seeded()
        assert target.read_text(encoding="utf-8") != first
        assert "user" in target.read_text(encoding="utf-8")
    finally:
        asset_store.genes_seed_path = original  # type: ignore[assignment]


def test_ensure_asset_files_creates_skeleton(assets_dir: Path) -> None:
    for child in list(assets_dir.iterdir()):
        if child.is_file():
            child.unlink()
    asset_store.ensure_asset_files()
    assert (assets_dir / "capsules.json").exists()
    assert (assets_dir / "failed_capsules.json").exists()


def test_capsule_jsonl_overlay(assets_dir: Path) -> None:
    asset_store.atomic_write_json(
        assets_dir / "capsules.json",
        {"version": 1, "capsules": [{"id": "c1", "type": "Capsule", "summary": "old"}]},
    )
    asset_store.append_jsonl(
        assets_dir / "capsules.jsonl",
        {"id": "c1", "type": "Capsule", "summary": "new"},
    )
    caps = asset_store.load_capsules()
    assert len(caps) == 1
    assert caps[0]["summary"] == "new"


# ---------------------------------------------------------------------------
# Events / failed / pending
# ---------------------------------------------------------------------------


def test_append_and_read_events(assets_dir: Path) -> None:
    asset_store.append_event_jsonl({"id": "evt1", "type": "EvolutionEvent"})
    asset_store.append_event_jsonl({"id": "evt2", "type": "EvolutionEvent"})
    events = asset_store.read_all_events()
    assert [e["id"] for e in events] == ["evt1", "evt2"]
    assert asset_store.get_last_event_id() == "evt2"


def test_failed_capsules_roundtrip(assets_dir: Path) -> None:
    asset_store.append_failed_capsule({"id": "f1", "reason": "boom"})
    recent = asset_store.read_recent_failed_capsules(10)
    assert recent[-1]["id"] == "f1"


def test_pending_signals_append_and_consume(assets_dir: Path) -> None:
    asset_store.append_pending_signals(["a", "b"])
    asset_store.append_pending_signals(["b", "c"])  # dedupe b
    signals = asset_store.consume_pending_signals()
    assert set(signals) == {"a", "b", "c"}
    assert asset_store.consume_pending_signals() == []


# ---------------------------------------------------------------------------
# File lock (#451)
# ---------------------------------------------------------------------------


def test_with_file_lock_serializes_critical_sections(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    active = {"n": 0, "max": 0}

    def job() -> None:
        with asset_store.with_file_lock(timeout=10.0, target_path=target):
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
            time.sleep(0.02)
            active["n"] -= 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: job(), range(16)))
    assert active["max"] == 1


def test_with_file_lock_releases_after_throw(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    with pytest.raises(RuntimeError, match="boom"):
        with asset_store.with_file_lock(target_path=target):
            raise RuntimeError("boom")
    entered = {"ok": False}
    with asset_store.with_file_lock(target_path=target):
        entered["ok"] = True
    assert entered["ok"] is True


def test_build_validation_cmd_allows_known_tools() -> None:
    assert asset_store.build_validation_cmd("pytest -q", Path("."))[:1] == ["pytest"]
    assert asset_store.build_validation_cmd("rm -rf /", Path(".")) == []
