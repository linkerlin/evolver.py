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
