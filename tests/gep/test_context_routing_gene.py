"""Claude context schema routing Gene family (v1.94.0 parity).

Behavioral port of Node ``test/contextSchemaRoutingGene.test.js`` (module part;
the signal extraction part lives with the signals tests).
"""

from __future__ import annotations

import json

from evolver.gep import asset_store
from evolver.gep.content_hash import verify_asset_id
from evolver.gep.context_routing_gene import (
    FAMILY_GENE_IDS,
    build_claude_context_gene_family,
    build_claude_context_schema_routing_gene,
)
from evolver.gep.schemas.gene import Gene, validate_gene
from evolver.gep.selector import select_gene
from evolver.gep.signals import extract_signals

EXPECTED_IDS = [
    "gene_claude_prompt_budget_ledger",
    "gene_claude_context_schema_routing",
    "gene_claude_tool_schema_lazy_load",
    "gene_claude_skill_manual_routing",
    "gene_claude_transcript_handoff_compression",
    "gene_claude_memory_index_budget",
]


class TestClaudeContextGeneFamily:
    def test_complete_content_addressed_family(self) -> None:
        genes = build_claude_context_gene_family()
        assert [g["id"] for g in genes] == EXPECTED_IDS
        for gene in genes:
            assert verify_asset_id(gene, gene["asset_id"]), gene["id"]
            assert gene["routing_hint"]["tier"] == "mid", gene["id"]
            assert len(gene["summary"]) >= 40, gene["id"]
            assert len(gene["strategy"]) >= 5, gene["id"]
            assert len(gene["validation"]) >= 2, gene["id"]
            assert validate_gene(Gene.model_validate(gene)) is True, gene["id"]

    def test_legacy_dispatcher_builder(self) -> None:
        assert build_claude_context_schema_routing_gene()["id"] == (
            "gene_claude_context_schema_routing"
        )

    def test_bundled_seed_carries_same_family(self) -> None:
        generated = build_claude_context_gene_family()
        seed = json.loads(asset_store.genes_seed_path().read_text(encoding="utf-8"))
        seed_genes = seed.get("genes", [])
        for gene in generated:
            found = next(
                (g for g in seed_genes if isinstance(g, dict) and g.get("id") == gene["id"]),
                None,
            )
            assert found is not None, f"bundled seed must include {gene['id']}"
            assert found["signals_match"] == gene["signals_match"], gene["id"]
            assert found["strategy"] == gene["strategy"], gene["id"]
            assert found["validation"] == gene["validation"], gene["id"]
            assert verify_asset_id(found, found["asset_id"]), gene["id"]

    def test_family_ids_constant(self) -> None:
        assert list(FAMILY_GENE_IDS) == EXPECTED_IDS


class TestContextBloatSignals:
    """Port of the extractSignals half of contextSchemaRoutingGene.test.js."""

    def test_deterministic_signals_from_natural_language(self) -> None:
        signals = extract_signals(
            recent_session_transcript="\n".join(
                [
                    "Claude Code context exploded after Available agent types and "
                    "MCP Server Instructions were injected.",
                    "The tool schema is too large, the skill manual descriptions are "
                    "too long, and we should distill it into a gene with lazy-load "
                    "schema routing.",
                    "工具 schema 太大，mcp/skill 列表太长，随便传一个会话上下文就爆了。",
                    "Build a prompt budget ledger and check whether the memory index "
                    "is still okay before blaming MEMORY.md.",
                ]
            ),
            today_log="",
            memory_snippet="",
            user_snippet="",
            recent_events=[],
        )
        for expected in (
            "claude_code_context_bloat",
            "context_explosion",
            "tool_schema_bloat",
            "skill_list_bloat",
            "skill_manual_bloat",
            "lazy_load_schema",
            "schema_routing_gene_request",
            "prompt_budget_measurement",
            "memory_index_budget",
            "conversation_handoff_bloat",
        ):
            assert expected in signals, f"missing signal {expected}"

    def test_selector_chooses_specialized_genes(self) -> None:
        family = build_claude_context_gene_family()
        generic = {
            "type": "Gene",
            "id": "gene_generic_prompt",
            "category": "optimize",
            "signals_match": ["prompt", "protocol"],
            "strategy": ["generic prompt optimization"],
            "validation": ['node -e "true"'],
        }
        cases = [
            (
                ["prompt_budget_measurement", "token_budget_overflow"],
                "gene_claude_prompt_budget_ledger",
            ),
            (
                ["claude_code_context_bloat", "schema_routing_gene_request"],
                "gene_claude_context_schema_routing",
            ),
            (
                ["tool_schema_bloat", "mcp_tool_schema", "lazy_load_schema"],
                "gene_claude_tool_schema_lazy_load",
            ),
            (["skill_manual_bloat", "skill_list_bloat"], "gene_claude_skill_manual_routing"),
            (
                ["transcript_context_bloat", "conversation_handoff_bloat"],
                "gene_claude_transcript_handoff_compression",
            ),
            (["memory_index_budget"], "gene_claude_memory_index_budget"),
        ]
        for signals, expected in cases:
            result = select_gene([generic, *family], signals, {})
            assert result["selected"] is not None, expected
            assert result["selected"]["id"] == expected
