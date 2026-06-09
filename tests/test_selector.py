"""Tests for evolver.gep.selector — equivalent to evolver/test/selector.test.js."""

from __future__ import annotations

import pytest

from evolver.gep import selector
from evolver.gep.env_fingerprint import capture_env_fingerprint

GENES = [
    {
        "type": "Gene",
        "id": "gene_repair",
        "category": "repair",
        "signals_match": ["error", "exception", "failed"],
        "strategy": ["fix it"],
        "validation": ["node -e \"true\""],
    },
    {
        "type": "Gene",
        "id": "gene_repair_fallback",
        "category": "repair",
        "signals_match": ["error", "exception", "failed"],
        "strategy": ["fallback fix"],
        "validation": ["node -e \"true\""],
    },
    {
        "type": "Gene",
        "id": "gene_optimize",
        "category": "optimize",
        "signals_match": ["protocol", "prompt", "audit"],
        "strategy": ["optimize it"],
        "validation": ["node -e \"true\""],
    },
    {
        "type": "Gene",
        "id": "gene_innovate",
        "category": "innovate",
        "signals_match": [
            "user_feature_request",
            "user_improvement_suggestion",
            "capability_gap",
            "stable_success_plateau",
        ],
        "strategy": ["build it"],
        "validation": ["node -e \"true\""],
    },
]


def test_select_gene_highest_match() -> None:
    result = selector.select_gene(GENES, ["error", "exception", "failed"], {})
    assert result["selected"]["id"] == "gene_repair"


def test_select_gene_no_match_returns_none() -> None:
    result = selector.select_gene(GENES, ["completely_unrelated_signal"], {})
    assert result["selected"] is None


def test_select_gene_returns_alternatives() -> None:
    result = selector.select_gene(GENES, ["error", "protocol"], {})
    assert result["selected"] is not None
    assert isinstance(result["alternatives"], list)


def test_select_gene_base_name_snippet() -> None:
    result = selector.select_gene(
        GENES, ["user_feature_request:add a dark mode toggle to the settings"], {}
    )
    assert result["selected"]["id"] == "gene_innovate"


def test_select_gene_banned_skipped() -> None:
    result = selector.select_gene(
        GENES,
        ["error", "exception", "failed"],
        {"bannedGeneIds": {"gene_repair"}},
    )
    assert result["selected"]["id"] != "gene_repair"


def test_select_capsule_matching_triggers() -> None:
    capsules = [
        {"id": "capsule_1", "trigger": ["log_error", "exception"]},
        {"id": "capsule_2", "trigger": ["protocol", "gep"]},
    ]
    result = selector.select_capsule(capsules, ["log_error", "exception"])
    assert result["id"] == "capsule_1"


def test_select_capsule_no_match_returns_none() -> None:
    capsules = [{"id": "capsule_1", "trigger": ["log_error"]}]
    result = selector.select_capsule(capsules, ["unrelated"])
    assert result is None


def test_tokenize_unicode() -> None:
    tokens = selector.tokenize("[错误] connection refused")
    assert "错误" in tokens
    assert "connection" in tokens


def test_is_epigenetically_suppressed() -> None:
    env = capture_env_fingerprint()
    key = f"{env['platform']}/{env['arch']}/{env['python_version']}"
    gene = {
        "id": "gene_dead",
        "epigenetic_marks": [{"context": key, "boost": -0.4}],
    }
    assert selector.is_epigenetically_suppressed(gene, env) is True


def test_is_epigenetically_suppressed_wrong_env() -> None:
    gene = {
        "id": "gene_other",
        "epigenetic_marks": [{"context": "aix/sparc/v0.0.0", "boost": -0.5}],
    }
    assert selector.is_epigenetically_suppressed(gene) is False
