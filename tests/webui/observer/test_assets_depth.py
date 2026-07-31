"""Depth tests for observer assets: overview, candidates, calls, lineage."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.webui.observer.assets import (
    get_asset_overview,
    get_lineage,
    list_asset_calls,
    list_candidates,
    serialize_assets,
)


def test_serialize_counts_by_category(tmp_path: Path) -> None:
    genes = {
        "genes": [
            {"id": "g1", "category": "repair", "solidified": True},
            {"id": "g2", "category": "innovate"},
        ]
    }
    (tmp_path / "genes.json").write_text(json.dumps(genes), encoding="utf-8")
    result = serialize_assets(assets_dir=tmp_path)
    assert result["counts"]["by_category"]["repair"] == 1
    assert result["counts"]["by_category"]["innovate"] == 1
    assert result["counts"]["solidified"] == 1


def test_asset_overview(tmp_path: Path, monkeypatch: object) -> None:
    genes = {"genes": [{"id": "g1", "category": "repair"}]}
    capsules = {"capsules": [{"id": "c1", "outcome": {"status": "success"}}]}
    (tmp_path / "genes.json").write_text(json.dumps(genes), encoding="utf-8")
    (tmp_path / "capsules.json").write_text(json.dumps(capsules), encoding="utf-8")
    (tmp_path / "candidates.jsonl").write_text(
        json.dumps({"id": "cand1", "summary": "local cand"}) + "\n", encoding="utf-8"
    )
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"type": "EvolutionEvent", "id": "e1", "gene_id": "g1"}) + "\n",
        encoding="utf-8",
    )
    # empty evolution call log
    evo = tmp_path / "evolution"
    evo.mkdir()
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))  # type: ignore[attr-defined]

    overview = get_asset_overview(assets_dir=tmp_path)
    assert overview["counts"]["genes"] == 1
    assert overview["counts"]["capsules"] == 1
    assert overview["counts"]["candidates"] == 1
    assert overview["counts"]["events"] == 1
    assert overview["genesByCategory"]["repair"] == 1
    assert overview["capsulesByOutcome"]["success"] == 1


def test_list_candidates_local_and_external(tmp_path: Path) -> None:
    (tmp_path / "candidates.jsonl").write_text(
        json.dumps({"id": "L1", "summary": "local"}) + "\n", encoding="utf-8"
    )
    (tmp_path / "external_candidates.jsonl").write_text(
        json.dumps({"id": "E1", "summary": "external"}) + "\n", encoding="utf-8"
    )
    result = list_candidates(assets_dir=tmp_path)
    assert result["total"] == 2
    sources = {it["source"] for it in result["items"]}
    assert sources == {"local", "external"}


def test_list_candidates_query(tmp_path: Path) -> None:
    (tmp_path / "candidates.jsonl").write_text(
        json.dumps({"id": "L1", "summary": "alpha"})
        + "\n"
        + json.dumps({"id": "L2", "summary": "beta"})
        + "\n",
        encoding="utf-8",
    )
    result = list_candidates(assets_dir=tmp_path, query="beta")
    assert result["total"] == 1
    assert result["items"][0]["id"] == "L2"


def test_list_asset_calls(tmp_path: Path, monkeypatch: object) -> None:
    evo = tmp_path / "evolution"
    evo.mkdir()
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))  # type: ignore[attr-defined]
    log = evo / "asset_call_log.jsonl"
    rows = [
        {"run_id": "r1", "action": "asset_reuse", "asset_id": "sha256:aaa"},
        {"run_id": "r2", "action": "hub_search_hit", "asset_id": "sha256:bbb"},
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    result = list_asset_calls(run_id="r1")
    assert result["total"] == 1
    assert result["items"][0]["action"] == "asset_reuse"


def test_get_lineage(tmp_path: Path, monkeypatch: object) -> None:
    genes = {"genes": [{"id": "g1", "summary": "root gene"}]}
    capsules = {
        "capsules": [
            {"id": "c1", "gene": "g1", "outcome": {"status": "success"}},
            {"id": "c2", "gene": "other"},
        ]
    }
    (tmp_path / "genes.json").write_text(json.dumps(genes), encoding="utf-8")
    (tmp_path / "capsules.json").write_text(json.dumps(capsules), encoding="utf-8")
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"type": "EvolutionEvent", "gene_id": "g1", "id": "e1"}) + "\n",
        encoding="utf-8",
    )
    evo = tmp_path / "evolution"
    evo.mkdir()
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))  # type: ignore[attr-defined]
    (evo / "asset_call_log.jsonl").write_text(
        json.dumps({"id": "g1", "action": "asset_inject", "asset_id": "sha256:g1"}) + "\n",
        encoding="utf-8",
    )

    lin = get_lineage("g1", assets_dir=tmp_path)
    assert len(lin["genes"]) == 1
    assert len(lin["capsules"]) == 1
    assert lin["capsules"][0]["id"] == "c1"
    assert len(lin["events"]) >= 1
