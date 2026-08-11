"""Conversation distiller unit tests (Sprint 15.4)."""

# ruff: noqa: E501

from __future__ import annotations

from evolver.gep.conversation_distiller import (
    distill_conversation,
    evaluate_gate,
    infer_signals,
    normalize_conversation_input,
)

VALID = {
    "summary": ("Reusable Evolver distill endpoint compatibility workflow for MCP plugin bridges."),
    "assistant_summary": (
        "Added a Proxy conversation distillation bridge so Codex, Claude Code, Cursor, "
        "WorkBuddy, and Antigravity plugins can publish Genes and Capsules without hitting a 404."
    ),
    "strategy": [
        "Verify each plugin bridge calls the same Proxy route before changing repository code.",
        "Keep the Proxy route on the current signed asset publish path instead of the old mailbox submit path.",
        "Add focused tests for draft distillation, publish forwarding, and low quality skipped inputs.",
    ],
    "artifacts": [
        "src/proxy/server/routes.js",
        "src/gep/conversationDistiller.js",
    ],
    "validation": ["node --test test/proxyServer.test.js"],
    "signals": ["distill_endpoint", "proxy_compatibility", "test_verified"],
}


def test_infers_distill_signals() -> None:
    sigs = infer_signals("We should distill a reusable gene from this workflow")
    assert "conversation_distillation" in sigs


def test_normalize_summary_and_strategy() -> None:
    norm = normalize_conversation_input(VALID)
    assert len(norm["summary"]) >= 40
    assert len(norm["strategy"]) >= 3
    assert norm["artifacts"]


def test_gate_rejects_low_score() -> None:
    norm = normalize_conversation_input({"summary": "x" * 50})
    gate = evaluate_gate({"summary": "x" * 50, "min_score": 5}, norm)
    assert gate["ok"] is False
    assert gate["reason"] == "insufficient_reusable_signal"


def test_distill_draft_ok() -> None:
    result = distill_conversation({**VALID, "persist": False}, persist=False)
    assert result["ok"] is True
    assert result["status"] == "draft"
    assert result["gene"]["type"] == "Gene"
    assert result["capsule"]["type"] == "Capsule"
    assert result["capsule"]["blast_radius"] == {"files": 1, "lines": 1}
    assert isinstance(result["capsule"]["content"], str)
    assert isinstance(result["capsule"]["diff"], str)
    assert isinstance(result["capsule"]["reused_asset_id"], str)
    assert isinstance(result["capsule"]["env_fingerprint"], dict)
    assert result["capsule"]["source_type"] == "conversation_distillation"
    assert result["gene"]["id"].startswith("gene_conversation_")
    assert result["capsule"]["gene"] == result["gene"]["id"]


def test_distill_skips_summary_required() -> None:
    result = distill_conversation({"summary": "too short"}, persist=False)
    assert result["ok"] is False
    assert result["status"] == "skipped"
    assert result["reason"] == "summary_required"


def test_distill_skips_low_signal() -> None:
    # Long enough for summary gate but no strategy/artifacts/distill keywords.
    result = distill_conversation(
        {
            "summary": "x" * 50,
            "persist": False,
            "min_score": 5,
        },
        persist=False,
    )
    assert result["ok"] is False
    assert result["status"] == "skipped"
    assert result["reason"] in ("insufficient_reusable_signal", "summary_required")


def test_distill_rejects_non_object() -> None:
    result = distill_conversation(None)  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["reason"] == "input_object_required"


# ---------------------------------------------------------------------------
# v1.93.0 meta self-reference gate (port of conversationDistiller.test.js)
# ---------------------------------------------------------------------------

META_ONLY = {
    "summary": (
        "We discussed how the evolver distills genes and whether reusing a gene "
        "about reusing genes is worth it."
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

DOMAIN = {
    "summary": (
        "Publish a markdown file as a Feishu doc via lark-cli and return the shareable url."
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

META_SIGNAL_SET = frozenset(
    {"conversation_distillation", "gene_publish", "agent_self_evolution", "reusable_capability"}
)


class TestMetaSelfReferenceGate:
    def test_rejects_meta_only_conversation(self) -> None:
        normalized = normalize_conversation_input(META_ONLY)
        gate = evaluate_gate(META_ONLY, normalized)
        assert gate["ok"] is False
        assert gate["reason"] == "meta_self_reference"
        for s in normalized["signals"]:
            assert s in META_SIGNAL_SET, f"unexpected non-meta signal leaked in: {s}"

    def test_passes_domain_conversation(self) -> None:
        normalized = normalize_conversation_input(DOMAIN)
        gate = evaluate_gate(DOMAIN, normalized)
        assert gate["ok"] is True, (
            f"expected pass, got {gate.get('reason')} score={gate.get('score')}"
        )

    def test_rejects_meta_discussion_despite_broad_signal_matches(self) -> None:
        data = {
            "summary": (
                "We discussed whether a reusable gene about reusing genes should be "
                "distilled into the evolver plugin test workflow."
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
        normalized = normalize_conversation_input(data)
        assert "reusable_capability" in normalized["signals"]
        assert "plugin_integration" in normalized["signals"]
        assert "test_verified" in normalized["signals"]
        gate = evaluate_gate(data, normalized)
        assert gate["ok"] is False
        assert gate["reason"] == "meta_self_reference"

    def test_rejects_meta_vocabulary_only_in_strategy_artifacts(self) -> None:
        data = {
            "summary": "We captured a repeatable workflow and debated whether it should be preserved.",
            "strategy": [
                "Discuss how gene distillation works in the evolver",
                "Debate whether this reusable gene should recall another reusable gene",
                "Verify the generic runner still starts with npm test",
            ],
            "artifacts": ["gene-reuse-notes"],
            "validation": ["npm test"],
            "platform": "claude-code",
        }
        normalized = normalize_conversation_input(data)
        assert "gene_publish" in normalized["signals"]
        assert "test_verified" in normalized["signals"]
        gate = evaluate_gate(data, normalized)
        assert gate["ok"] is False
        assert gate["reason"] == "meta_self_reference"

    def test_rejects_caller_supplied_meta_signals_without_literal_vocabulary(self) -> None:
        data = {
            "summary": "We discussed whether this reusable workflow should be stored for later recall.",
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
        normalized = normalize_conversation_input(data)
        gate = evaluate_gate(data, normalized)
        assert gate["ok"] is False
        assert gate["reason"] == "meta_self_reference"

    def test_generated_fallback_strategy_not_domain_evidence(self) -> None:
        data = {
            "summary": "We discussed whether reusing a gene about reusing genes is worth distilling in evolver.",
            "artifacts": ["gene-reuse-notes"],
            "validation": ["node --version"],
            "platform": "claude-code",
        }
        normalized = normalize_conversation_input(data)
        assert any("Proxy" in step and "Hub" in step for step in normalized["strategy"])
        gate = evaluate_gate(data, normalized)
        assert gate["ok"] is False
        assert gate["reason"] == "meta_self_reference"

    def test_rejects_meta_despite_incidental_strong_signals(self) -> None:
        data = {
            "summary": "We discussed whether a reusable gene about reusing genes should be distilled.",
            "strategy": [
                "Mock the interaction between two capsules while debating the gene recall loop",
                "Capture a visual note about whether reusable genes should recall reusable genes",
                "Run npm test as a generic check",
            ],
            "artifacts": ["gene-reuse-notes"],
            "validation": ["npm test"],
            "platform": "claude-code",
        }
        normalized = normalize_conversation_input(data)
        assert "frontend_polish" in normalized["signals"]
        assert "visual_annotation" in normalized["signals"]
        gate = evaluate_gate(data, normalized)
        assert gate["ok"] is False
        assert gate["reason"] == "meta_self_reference"

    def test_passes_concrete_work_even_with_long_filler(self) -> None:
        data = {
            "summary": "Discuss gene distillation behavior. " + "padding " * 1500,
            "strategy": [
                "Preserve filler context before the concrete file evidence. " + "detail " * 30,
            ]
            * 9
            + ["Update src/gep/conversationDistiller.js after the long transcript context"],
            "artifacts": ["src/gep/conversationDistiller.js", "test/conversationDistiller.test.js"],
            "validation": ["node --test test/conversationDistiller.test.js"],
            "platform": "claude-code",
        }
        normalized = normalize_conversation_input(data)
        assert "src/gep/conversationDistiller.js" not in normalized["evidence_text"]
        assert any(
            "src/gep/conversationDistiller.js" in part for part in normalized["evidence_parts"]
        )
        gate = evaluate_gate(data, normalized)
        assert gate["ok"] is True, (
            f"expected pass, got {gate.get('reason')} score={gate.get('score')}"
        )

    def test_passes_concrete_gep_engineering_with_meta_words(self) -> None:
        data = {
            "summary": (
                "Fix src/gep/conversationDistiller.js so gene distillation keeps real "
                "GEP engineering work but rejects meta-only reuse loops."
            ),
            "strategy": [
                "Update src/gep/conversationDistiller.js with concrete domain evidence checks",
                "Add regression coverage in test/conversationDistiller.test.js",
                "Run node --test test/conversationDistiller.test.js",
            ],
            "artifacts": ["src/gep/conversationDistiller.js", "test/conversationDistiller.test.js"],
            "validation": ["node --test test/conversationDistiller.test.js"],
            "platform": "claude-code",
        }
        normalized = normalize_conversation_input(data)
        gate = evaluate_gate(data, normalized)
        assert gate["ok"] is True, (
            f"expected pass, got {gate.get('reason')} score={gate.get('score')}"
        )

    def test_passes_domain_source_text_with_meta_wording(self) -> None:
        data = {
            "summary": (
                "Discuss whether the frontend interaction workflow should be distilled "
                "as a reusable gene after verifying the share URL."
            ),
            "strategy": [
                "Render markdown for Feishu",
                "Call lark-cli docs +create",
                "Verify the share URL resolves",
            ],
            "artifacts": ["publish-feishu-doc.md"],
            "validation": ["lark-cli auth status"],
            "platform": "claude-code",
        }
        normalized = normalize_conversation_input(data)
        assert "frontend_polish" in normalized["source_signals"]
        gate = evaluate_gate(data, normalized)
        assert gate["ok"] is True, (
            f"expected pass, got {gate.get('reason')} score={gate.get('score')}"
        )

    def test_no_explicit_distill_signal_bonus(self) -> None:
        with_meta_words = dict(DOMAIN)
        with_meta_words["summary"] = (
            DOMAIN["summary"] + " We also distilled this into a reusable gene for evomap."
        )
        normalized = normalize_conversation_input(with_meta_words)
        gate = evaluate_gate(with_meta_words, normalized)
        assert "explicit_distill_signal" not in gate["reasons"], (
            "the +2 self-referential bonus must be gone"
        )


class TestInferSignalsNoSelfLabel:
    def test_signal_less_conversation_not_tagged_with_meta_signals(self) -> None:
        signals = infer_signals("xyzzy plugh frobnicate", [])
        assert "agent_self_evolution" not in signals
        assert "conversation_distillation" not in signals
        assert "gene_publish" not in signals


class TestDistillGateWiring:
    def test_skips_meta_only_without_persisting(self) -> None:
        result = distill_conversation(META_ONLY, persist=False)
        assert result["ok"] is False
        assert result["status"] == "skipped"
        assert result["reason"] == "meta_self_reference"

    def test_distils_domain_conversation(self) -> None:
        result = distill_conversation(DOMAIN, persist=False)
        assert result["ok"] is True, f"expected ok, got {result.get('reason')}"
        assert result["status"] == "draft"
        assert result["gene"]["id"].startswith("gene_conversation_")
