"""Ports Node ``test/syncAsset.test.js`` for prepare_sync_asset."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep.content_hash import verify_asset_id
from evolver.gep.schemas.gene import VALID_CATEGORIES, create_gene, validate_gene
from evolver.gep.sync_asset import install_sync_asset, prepare_sync_asset

CONTEXT = {
    "assetId": "hub_asset_1",
    "localId": "local_fallback",
    "summary": "list summary",
    "syncedAt": "2026-07-13T00:00:00.000Z",
}


def test_preserves_standard_gene_fields_and_adds_sync_metadata() -> None:
    payload = {
        "type": "Gene",
        "id": "gene_standard",
        "category": "repair",
        "signals_match": ["timeout", "http_500"],
        "strategy": ["Inspect logs", "Apply fix"],
        "validation": ["node --test"],
        "preconditions": ["Reproduction exists"],
        "constraints": {"max_files": 3, "forbidden_paths": [".git", "secrets"]},
        "anti_patterns": ["blind retry"],
        "routing_hint": {"tier": "mid", "reasoning_level": "high"},
        "tool_policy": {"deny": ["shell"], "severity": "block"},
        "schema_version": "1.8.0",
        "summary": "standard gene",
        "epigenetic_marks": [{"mark": "verified"}],
        "learning_history": [{"outcome": "success"}],
        "trigger": "manual_review",
        "parent": "sha256:parent",
        "postconditions": ["policy applied"],
        "metadata": {"author": "hub"},
        "performance_metrics": {"success_rate": 0.99},
        "anti_pattern": True,
        "failure_reason": "unsafe default",
        "model_name": "evox-test",
        "domain": "governance",
        "asset_id": "sha256:" + "0" * 64,
    }
    result = prepare_sync_asset({**CONTEXT, "assetType": "Gene", "payload": payload})
    assert result["id"] == payload["id"]
    assert result["schema_version"] == payload["schema_version"]
    assert result["signals_match"] == payload["signals_match"]
    assert result["preconditions"] == payload["preconditions"]
    assert result["constraints"] == payload["constraints"]
    assert result["anti_patterns"] == payload["anti_patterns"]
    assert result["routing_hint"] == payload["routing_hint"]
    assert result["tool_policy"] == payload["tool_policy"]
    assert result["validation"] == payload["validation"]
    for field in (
        "trigger",
        "parent",
        "postconditions",
        "metadata",
        "performance_metrics",
        "anti_pattern",
        "failure_reason",
        "model_name",
        "domain",
    ):
        assert result[field] == payload[field], field
    assert result["hub_asset_id"] == CONTEXT["assetId"]
    assert result["synced_at"] == CONTEXT["syncedAt"]
    assert result["asset_id"] != payload["asset_id"]
    assert verify_asset_id(result, result["asset_id"])
    assert "signals" not in result


def test_accepts_hub_regulatory_genes_with_string_triggers() -> None:
    result = prepare_sync_asset(
        {
            **CONTEXT,
            "assetType": "Gene",
            "payload": {
                "id": "gene_regulatory",
                "category": "regulatory",
                "signals_match": ["policy_violation"],
                "trigger": "manual_review",
                "strategy": ["enforce policy"],
            },
        }
    )
    assert result["category"] == "regulatory"
    assert result["trigger"] == "manual_review"
    assert verify_asset_id(result, result["asset_id"])


def test_keeps_regulatory_exception_out_of_standard_gene_apis() -> None:
    assert "regulatory" not in VALID_CATEGORIES
    assert create_gene({"category": "regulatory"}).category == "innovate"
    gene = create_gene(
        {
            "id": "gene_regulatory",
            "category": "innovate",
            "signals_match": [],
            "strategy": [],
        }
    )
    # Bypass pydantic assignment to inject Hub-only category into standard API.
    gene.__dict__["category"] = "regulatory"
    with pytest.raises(ValueError, match=r"Gene\.category must be one of"):
        validate_gene(gene)


def test_defaults_optional_hub_array_fields_when_omitted() -> None:
    gene = prepare_sync_asset(
        {
            **CONTEXT,
            "assetType": "Gene",
            "payload": {
                "id": "gene_without_strategy",
                "category": "repair",
                "signals_match": ["timeout"],
            },
        }
    )
    capsule = prepare_sync_asset(
        {
            **CONTEXT,
            "assetType": "Capsule",
            "payload": {
                "id": "capsule_without_trace",
                "outcome": {"status": "success"},
            },
        }
    )
    assert gene["strategy"] == []
    assert capsule["trigger"] == []
    assert capsule["execution_trace"] == []


def test_rejects_gene_missing_signals_match() -> None:
    with pytest.raises(ValueError, match=r"Gene\.signals_match must be an array"):
        prepare_sync_asset(
            {
                **CONTEXT,
                "assetType": "Gene",
                "payload": {
                    "id": "gene_legacy",
                    "category": "repair",
                    "signals": ["error"],
                    "strategy": ["fix"],
                },
            }
        )


def test_rejects_malformed_gene_fields() -> None:
    with pytest.raises(ValueError, match=r"Gene\.signals_match must be an array"):
        prepare_sync_asset(
            {
                **CONTEXT,
                "assetType": "Gene",
                "payload": {
                    "id": "gene_bad",
                    "category": "repair",
                    "signals_match": "error",
                    "strategy": [],
                },
            }
        )
    with pytest.raises(ValueError, match=r"Gene\.constraints must be an object"):
        prepare_sync_asset(
            {
                **CONTEXT,
                "assetType": "Gene",
                "payload": {
                    "id": "gene_bad",
                    "category": "repair",
                    "signals_match": [],
                    "strategy": [],
                    "constraints": [],
                },
            }
        )
    with pytest.raises(ValueError, match=r"Gene\.routing_hint\.tier must be one of"):
        prepare_sync_asset(
            {
                **CONTEXT,
                "assetType": "Gene",
                "payload": {
                    "id": "gene_bad",
                    "category": "repair",
                    "signals_match": [],
                    "strategy": [],
                    "routing_hint": {"tier": "unlimited"},
                },
            }
        )
    with pytest.raises(ValueError, match=r"Gene\.trigger must be a string"):
        prepare_sync_asset(
            {
                **CONTEXT,
                "assetType": "Gene",
                "payload": {
                    "id": "gene_bad",
                    "category": "repair",
                    "signals_match": [],
                    "strategy": [],
                    "trigger": ["manual_review"],
                },
            }
        )


def test_preserves_standard_capsule_fields() -> None:
    payload = {
        "type": "Capsule",
        "id": "capsule_standard",
        "schema_version": "1.8.0",
        "trigger": ["timeout"],
        "gene": "gene_standard",
        "genes_used": ["gene_standard"],
        "summary": "standard capsule",
        "confidence": 0.9,
        "blast_radius": {"files": 2, "lines": 12},
        "outcome": {"status": "success", "score": 0.95},
        "env_fingerprint": {"platform": "darwin", "arch": "arm64"},
        "success_streak": 2,
        "success_reason": "tests passed",
        "source_type": "reused",
        "reused_asset_id": "sha256:source",
        "a2a": {"eligible_to_broadcast": True},
        "strategy": ["apply fix"],
        "execution_trace": [{"command": "node --test", "exit_code": 0}],
        "visibility": "private",
        "scope": ["repo"],
        "cost_tier": "standard",
        "pack_of": ["pack_1"],
        "author": {"handle": "tester", "evox_install_id": "install_1"},
        "parent": "sha256:parent",
        "validation": ["node --test"],
        "code_snippet": "return safeValue;",
        "content": "safe markdown content",
        "diff": "diff --git a/src/example.js b/src/example.js",
        "preconditions": ["clean worktree"],
        "postconditions": ["tests pass"],
        "metadata": {"tags": ["sync"]},
        "performance_metrics": {"latency_ms": 12},
        "capsule_id": "capsule_alias",
        "failure_reason": "previous timeout",
        "diff_snapshot": "diff --git a/a b/a",
        "lesson_learned": "validate before write",
        "model_name": "evox-test",
        "trigger_context": {"prompt": "repair timeout", "context_signals": ["timeout"]},
        "skills_used": [{"type": "internal", "skill_id": "debugging", "name": "Debugging"}],
        "domain": "backend",
        "asset_id": "sha256:" + "1" * 64,
    }
    result = prepare_sync_asset({**CONTEXT, "assetType": "Capsule", "payload": payload})
    for field in (
        "schema_version",
        "trigger",
        "gene",
        "genes_used",
        "confidence",
        "blast_radius",
        "outcome",
        "env_fingerprint",
        "success_streak",
        "success_reason",
        "source_type",
        "reused_asset_id",
        "a2a",
        "strategy",
        "execution_trace",
        "visibility",
        "scope",
        "cost_tier",
        "pack_of",
        "author",
        "parent",
        "validation",
        "code_snippet",
        "content",
        "diff",
        "preconditions",
        "postconditions",
        "metadata",
        "performance_metrics",
        "capsule_id",
        "failure_reason",
        "diff_snapshot",
        "lesson_learned",
        "model_name",
        "trigger_context",
        "skills_used",
        "domain",
    ):
        assert result[field] == payload[field], field
    assert result["hub_asset_id"] == CONTEXT["assetId"]
    assert result["synced_at"] == CONTEXT["syncedAt"]
    assert result["asset_id"] != payload["asset_id"]
    assert verify_asset_id(result, result["asset_id"])


@pytest.mark.parametrize("source_type", ["skill2gep_hook", "conversation_distillation"])
def test_preserves_hub_capsule_source_types(source_type: str) -> None:
    result = prepare_sync_asset(
        {
            **CONTEXT,
            "assetType": "Capsule",
            "payload": {
                "id": f"capsule_{source_type}",
                "outcome": {"status": "success"},
                "source_type": source_type,
            },
        }
    )
    assert result["source_type"] == source_type
    assert verify_asset_id(result, result["asset_id"])


def test_copies_only_explicit_contract_fields() -> None:
    payload = json.loads(
        '{"id":"gene_safe","category":"repair","signals_match":["error"],'
        '"strategy":["fix"],"constructor":{"polluted":true},'
        '"prototype":{"polluted":true},"unknown_field":"drop"}'
    )
    result = prepare_sync_asset({**CONTEXT, "assetType": "Gene", "payload": payload})
    assert type(result) is dict
    assert "constructor" not in result
    assert "prototype" not in result
    assert "unknown_field" not in result
    assert not hasattr(type(result), "polluted")


def test_rejects_malformed_capsule_payloads() -> None:
    with pytest.raises(ValueError, match=r"Capsule\.outcome\.status must be one of"):
        prepare_sync_asset(
            {
                **CONTEXT,
                "assetType": "Capsule",
                "payload": {
                    "id": "capsule_bad",
                    "outcome": {},
                    "trigger": [],
                    "execution_trace": [],
                },
            }
        )
    with pytest.raises(ValueError, match=r"Capsule\.trigger must be an array"):
        prepare_sync_asset(
            {
                **CONTEXT,
                "assetType": "Capsule",
                "payload": {
                    "id": "capsule_bad",
                    "outcome": {"status": "success"},
                    "trigger": "timeout",
                    "execution_trace": [],
                },
            }
        )
    with pytest.raises(ValueError, match=r"Capsule\.visibility must be one of"):
        prepare_sync_asset(
            {
                **CONTEXT,
                "assetType": "Capsule",
                "payload": {
                    "id": "capsule_bad",
                    "outcome": {"status": "success"},
                    "trigger": [],
                    "execution_trace": [],
                    "visibility": "everyone",
                },
            }
        )
    for source_type in (42, "", " padded ", "x" * 129, "line\nbreak"):
        with pytest.raises(ValueError, match=r"Capsule\.source_type must be null"):
            prepare_sync_asset(
                {
                    **CONTEXT,
                    "assetType": "Capsule",
                    "payload": {
                        "id": "capsule_bad_source_type",
                        "outcome": {"status": "success"},
                        "source_type": source_type,
                    },
                }
            )


def test_uses_local_id_and_list_summary_when_payload_omits() -> None:
    result = prepare_sync_asset(
        {
            **CONTEXT,
            "assetType": "Gene",
            "payload": {"category": "optimize", "signals_match": [], "strategy": []},
        }
    )
    assert result["id"] == CONTEXT["localId"]
    assert result["summary"] == CONTEXT["summary"]


def test_requires_synced_at() -> None:
    with pytest.raises(ValueError, match="syncedAt is required"):
        prepare_sync_asset(
            {
                "assetType": "Gene",
                "assetId": CONTEXT["assetId"],
                "localId": CONTEXT["localId"],
                "payload": {"category": "repair", "signals_match": [], "strategy": []},
            }
        )


def test_install_force_overwrites_local_gene_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path
    monkeypatch.setenv("GEP_ASSETS_DIR", str(root / "gep"))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(root))

    gene_a = prepare_sync_asset(
        {
            **CONTEXT,
            "assetType": "Gene",
            "payload": {
                "id": "gene_conflict",
                "category": "repair",
                "signals_match": ["a"],
                "strategy": ["old"],
            },
        }
    )
    first = install_sync_asset(gene_a, force=False)
    assert first["ok"] is True

    gene_b = prepare_sync_asset(
        {
            **CONTEXT,
            "assetId": "hub_asset_2",
            "assetType": "Gene",
            "payload": {
                "id": "gene_conflict",
                "category": "repair",
                "signals_match": ["b"],
                "strategy": ["new"],
            },
        }
    )
    blocked = install_sync_asset(gene_b, force=False)
    assert blocked["ok"] is False
    assert blocked["error"] == "local_id_conflict"

    forced = install_sync_asset(gene_b, force=True)
    assert forced["ok"] is True
    assert forced["forced"] is True
