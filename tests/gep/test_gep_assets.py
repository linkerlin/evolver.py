"""Tests for evolver.gep.assets."""

from __future__ import annotations

from evolver.gep.assets import (
    BEDROCK_MODEL_MAP,
    canonicalize_for_bedrock,
    canonicalize_model,
    format_asset_list,
    format_capsule_preview,
    format_gene_preview,
    truncate_asset_id,
)


class TestModelCanonicalization:
    def test_known_mapping(self):
        mapped = canonicalize_for_bedrock("claude-3-5-sonnet-20241022")
        assert mapped == BEDROCK_MODEL_MAP["claude-3-5-sonnet-20241022"]

    def test_unknown_returns_as_is(self):
        assert canonicalize_for_bedrock("custom-model") == "custom-model"

    def test_all_mappings_present(self):
        for anthropic_id, bedrock_id in BEDROCK_MODEL_MAP.items():
            assert canonicalize_for_bedrock(anthropic_id) == bedrock_id
            assert bedrock_id.startswith("anthropic.")

    def test_canonicalize_model_alias(self):
        assert canonicalize_model("claude-3-haiku-20240307") == canonicalize_for_bedrock(
            "claude-3-haiku-20240307"
        )


class TestFormatGenePreview:
    def test_full_gene(self):
        gene = {
            "id": "g-12",
            "category": "repair",
            "risk_level": "low",
            "score": 85,
            "summary": "Fix timeout in HTTP client",
        }
        result = format_gene_preview(gene)
        assert "[low]" in result
        assert "g-12" in result
        assert "repair" in result
        assert "score=85" in result
        assert "Fix timeout" in result

    def test_minimal_gene(self):
        gene = {"id": "g-1", "category": "optimize"}
        result = format_gene_preview(gene)
        assert "g-1" in result
        assert "optimize" in result

    def test_long_summary_truncated(self):
        gene = {"id": "g-x", "summary": "A" * 200}
        result = format_gene_preview(gene)
        summary_start = result.index("— ") + 2
        assert len(result[summary_start:]) <= 80


class TestFormatCapsulePreview:
    def test_full_capsule(self):
        capsule = {
            "id": "c-1",
            "type": "patch",
            "source": "hub",
            "gene_id": "g-12",
        }
        result = format_capsule_preview(capsule)
        assert "c-1" in result
        assert "patch" in result
        assert "g-12" in result


class TestFormatAssetList:
    def test_empty(self):
        assert format_asset_list([]) == "No genes found."

    def test_with_genes(self):
        genes = [{"id": f"g-{i}", "category": "repair"} for i in range(3)]
        result = format_asset_list(genes, asset_type="gene")
        assert "3 gene(s)" in result
        for i in range(3):
            assert f"g-{i}" in result

    def test_capsule_list(self):
        caps = [{"id": "c-1", "type": "patch"}] * 5
        result = format_asset_list(caps, asset_type="capsule")
        assert "5 capsule(s)" in result

    def test_truncates_at_20(self):
        genes = [{"id": f"g-{i}"} for i in range(25)]
        result = format_asset_list(genes)
        assert "and 5 more" in result


class TestTruncateAssetId:
    def test_sha256(self):
        result = truncate_asset_id("sha256:abcdef1234567890abcdef1234567890abcdef1234567890abcdef")
        assert result.startswith("sha256:")
        assert result.endswith("…")

    def test_short_sha256(self):
        result = truncate_asset_id("sha256:abc123")
        assert result == "sha256:abc123"

    def test_plain_id(self):
        result = truncate_asset_id("gene-r7")
        assert result == "gene-r7"

    def test_long_plain_id(self):
        result = truncate_asset_id("very-long-asset-id-that-exceeds-limit")
        assert result.endswith("…")
        assert len(result) == 13

    def test_empty(self):
        assert truncate_asset_id("") == "?"
