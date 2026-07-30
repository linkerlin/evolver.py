"""Meta self-reference gate tests for conversation distiller.

Equivalent to ``evolver/test/conversationDistiller.test.js`` (v1.93.0, 257 lines).

Ensures the conversation distiller rejects meta-only self-referential
discussions (genes about genes) while preserving real domain work.
"""

from __future__ import annotations

import pytest

from evolver.gep.conversation_distiller import (
    distill_conversation,
    evaluate_gate,
    infer_signals,
    normalize_conversation_input,
)

_META_ONLY = {
    "summary": (
        "We discussed how the evolver distills genes and whether "
        "reusing a gene about reusing genes is worth it."
    ),
    "strategy": [
        "Talk about how gene distillation works in evolver",
        "Debate whether capsules should be recalled again",
        "Decide the evomap self-evolution loop needs a guard",
    ],
    "artifacts": ["notes-about-genes.md"],
    "validation": ["node --version"],
    "platform": "claude-code",
}

_DOMAIN = {
    "summary": (
        "Publish a markdown file as a Feishu doc via lark-cli and "
        "return the shareable url."
    ),
    "strategy": [
        "Render the markdown body with the im-markdown format",
        "Call lark-cli docs +create with the rendered content",
        "Verify the returned url resolves before reporting success",
    ],
    "artifacts": ["publish-feishu-doc.md"],
    "validation": ["lark-cli auth status"],
    "platform": "claude-code",
}


class TestEvaluateGate:
    def test_rejects_meta_only(self) -> None:
        normalized = normalize_conversation_input(_META_ONLY)
        gate = evaluate_gate(_META_ONLY, normalized)
        assert gate["ok"] is False
        assert gate["reason"] == "meta_self_reference"

    def test_passes_real_domain(self) -> None:
        normalized = normalize_conversation_input(_DOMAIN)
        gate = evaluate_gate(_DOMAIN, normalized)
        assert gate["ok"] is True, f"expected pass, got {gate.get('reason')}"

    def test_meta_even_with_broad_signals(self) -> None:
        inp = {
            "summary": (
                "We discussed whether a reusable gene about reusing genes "
                "should be distilled into the evolver plugin test workflow."
            ),
            "strategy": [
                "Talk about how the evolver plugin recalls reusable genes",
                "Debate whether this repeatable gene workflow is self-referential",
                "Verify with node --version that the test environment exists",
            ],
            "artifacts": ["gene-reuse-notes.md"],
            "validation": ["node --version"],
            "platform": "claude-code",
        }
        normalized = normalize_conversation_input(inp)
        gate = evaluate_gate(inp, normalized)
        assert gate["ok"] is False
        assert gate["reason"] == "meta_self_reference"

    def test_meta_only_appears_in_strategy(self) -> None:
        inp = {
            "summary": (
                "We captured a repeatable workflow and debated whether "
                "it should be preserved."
            ),
            "strategy": [
                "Discuss how gene distillation works in the evolver",
                "Debate whether this reusable gene should recall another reusable gene",
                "Verify the generic runner still starts with npm test",
            ],
            "artifacts": ["gene-reuse-notes"],
            "validation": ["npm test"],
            "platform": "claude-code",
        }
        normalized = normalize_conversation_input(inp)
        gate = evaluate_gate(inp, normalized)
        assert gate["ok"] is False
        assert gate["reason"] == "meta_self_reference"

    def test_caller_supplied_meta_signals(self) -> None:
        inp = {
            "summary": (
                "We discussed whether this reusable workflow should be "
                "stored for later recall."
            ),
            "signals": ["gene_publish"],
            "strategy": [
                "Talk about the storage rule",
                "Debate whether a reusable workflow about reusable workflows is valuable",
                "Run npm run build as a generic check",
            ],
            "artifacts": ["reuse-policy-notes"],
            "validation": ["npm run build"],
            "platform": "claude-code",
        }
        normalized = normalize_conversation_input(inp)
        gate = evaluate_gate(inp, normalized)
        assert gate["ok"] is False
        assert gate["reason"] == "meta_self_reference"

    def test_passes_concrete_gep_engineering(self) -> None:
        inp = {
            "summary": (
                "Fix src/gep/conversationDistiller.js so gene distillation "
                "keeps real GEP engineering work but rejects meta-only reuse loops."
            ),
            "strategy": [
                "Update src/gep/conversationDistiller.js",
                "Add regression coverage in test/conversationDistiller.test.js",
                "Run node --test test/conversationDistiller.test.js",
            ],
            "artifacts": [
                "src/gep/conversationDistiller.js",
                "test/conversationDistiller.test.js",
            ],
            "validation": ["node --test test/conversationDistiller.test.js"],
            "platform": "claude-code",
        }
        normalized = normalize_conversation_input(inp)
        gate = evaluate_gate(inp, normalized)
        assert gate["ok"] is True, f"expected pass, got {gate.get('reason')}"


class TestInferSignals:
    def test_signal_less_not_meta_self_labeled(self) -> None:
        signals = infer_signals("xyzzy plugh frobnicate", None)
        assert "agent_self_evolution" not in signals
        assert "conversation_distillation" not in signals
        assert "gene_publish" not in signals


class TestDistillConversation:
    def test_skips_meta_only(self) -> None:
        res = distill_conversation(_META_ONLY, persist=False)
        assert res["ok"] is False
        assert res["status"] == "skipped"
        assert res["reason"] == "meta_self_reference"

    def test_distills_real_domain(self) -> None:
        res = distill_conversation(_DOMAIN, persist=False)
        assert res["ok"] is True, f"expected ok, got {res.get('reason')}"
        assert res["status"] == "draft"
        assert res.get("gene") and res["gene"].get("id"), "a gene should be produced"
