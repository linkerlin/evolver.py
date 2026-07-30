"""Tests for A2A asset gate."""
from __future__ import annotations
import json
from evolver.gep.a2a_gate import (
    ALLOWED_A2A_ASSET_TYPES, clamp01, export_eligible_genes,
    get_blast_radius_limits, is_allowed_a2a_asset, is_blast_radius_safe,
    is_capsule_broadcast_eligible, is_gene_broadcast_eligible,
    lower_confidence, parse_a2a_input, safe_number,
)

class TestIsAllowedA2AAsset:
    def test_gene(self) -> None:
        assert is_allowed_a2a_asset({"type": "Gene"})
    def test_capsule(self) -> None:
        assert is_allowed_a2a_asset({"type": "Capsule"})
    def test_event(self) -> None:
        assert is_allowed_a2a_asset({"type": "EvolutionEvent"})
    def test_unknown(self) -> None:
        assert not is_allowed_a2a_asset({"type": "Bogus"})
    def test_nondict(self) -> None:
        assert not is_allowed_a2a_asset(None)

class TestSafeNumber:
    def test_finite(self) -> None:
        assert safe_number(3.14) == 3.14
    def test_inf(self) -> None:
        assert safe_number(float("inf")) is None

class TestBlastRadius:
    def test_defaults(self) -> None:
        l = get_blast_radius_limits()
        assert l["maxFiles"] == 5 and l["maxLines"] == 200
    def test_safe(self) -> None:
        assert is_blast_radius_safe({"files": 3, "lines": 100})
    def test_exceed(self) -> None:
        assert not is_blast_radius_safe({"files": 99, "lines": 1})
    def test_none(self) -> None:
        assert is_blast_radius_safe(None)

class TestClamp01:
    def test_range(self) -> None:
        assert clamp01(0.5) == 0.5
    def test_below(self) -> None:
        assert clamp01(-0.5) == 0.0
    def test_above(self) -> None:
        assert clamp01(1.5) == 1.0
    def test_nan(self) -> None:
        assert clamp01(float("nan")) == 0.0

class TestLowerConfidence:
    def test_scale(self) -> None:
        r = lower_confidence({"type": "Capsule", "id": "c1", "confidence": 1.0})
        assert r is not None and r["confidence"] == 0.6
    def test_gene_not_null(self) -> None:
        r = lower_confidence({"type": "Gene", "id": "g1"})
        assert r is not None and r["a2a"]["status"] == "external_candidate"
    def test_bogus_null(self) -> None:
        assert lower_confidence({"type": "Bogus"}) is None
    def test_original_unchanged(self) -> None:
        o = {"type": "Capsule", "confidence": 1.0, "id": "c1"}
        lower_confidence(o)
        assert o["confidence"] == 1.0

class TestCapsuleEligible:
    def test_not_capsule(self) -> None:
        assert not is_capsule_broadcast_eligible(None)
    def test_low_score(self) -> None:
        assert not is_capsule_broadcast_eligible(
            {"type": "Capsule", "id": "c1", "outcome": {"score": 0.5}})
    def test_large_blast(self) -> None:
        assert not is_capsule_broadcast_eligible({
            "type": "Capsule", "id": "c1", "outcome": {"score": 0.8},
            "blast_radius": {"files": 99, "lines": 99}})

class TestGeneEligible:
    def test_valid(self) -> None:
        g = {"type": "Gene", "id": "g1", "strategy": ["s"], "validation": ["v"]}
        assert is_gene_broadcast_eligible(g)
    def test_no_strategy(self) -> None:
        assert not is_gene_broadcast_eligible(
            {"type": "Gene", "id": "g1", "validation": ["v"]})
    def test_no_validation(self) -> None:
        assert not is_gene_broadcast_eligible(
            {"type": "Gene", "id": "g1", "strategy": ["s"]})

class TestExportGenes:
    def test_empty(self) -> None:
        assert export_eligible_genes({"genes": []}) == []
    def test_mixed(self) -> None:
        gs = [
            {"type": "Gene", "id": "g1", "strategy": ["s"], "validation": ["v"]},
            {"type": "Gene", "id": "g2", "strategy": [], "validation": ["v"]},
        ]
        r = export_eligible_genes({"genes": gs})
        assert len(r) == 1 and r[0]["id"] == "g1"

class TestParseA2AInput:
    def test_empty(self) -> None:
        assert parse_a2a_input("") == []
    def test_single(self) -> None:
        assert parse_a2a_input('{"type":"Gene","id":"g1"}') == [{"type": "Gene", "id": "g1"}]
    def test_array(self) -> None:
        r = parse_a2a_input('[{"type":"Gene"},{"type":"Capsule"}]')
        assert len(r) == 2
    def test_jsonl(self) -> None:
        r = parse_a2a_input('{"type":"Gene"}\n{"type":"Capsule"}')
        assert len(r) == 2
