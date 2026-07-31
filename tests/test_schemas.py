"""Tests for GEP schemas — equivalent to evolver/test/schema*.test.js."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep.prompt import build_gep_prompt
from evolver.gep.schemas import (
    create_capsule,
    create_gene,
    create_task,
    validate_capsule,
    validate_gene,
    validate_task,
)
from evolver.gep.schemas import capsule as capsule_mod
from evolver.gep.schemas import gene as gene_mod
from evolver.gep.schemas.protocol import (
    VALID_CATEGORIES,
    VALID_OUTCOME_STATUSES,
    VALID_RISK_LEVELS,
    VALID_TRACE_STAGES,
    render_enum,
    render_enum_list,
)


def _build_minimal_prompt(**overrides: object) -> str:
    defaults = {
        "now_iso": "2026-01-01T00:00:00.000Z",
        "context": "",
        "signals": ["test_signal"],
        "selector": {"selectedBy": "test"},
        "parent_event_id": None,
        "selected_gene": None,
        "capsule_candidates": "(none)",
        "genes_preview": "[]",
        "capsules_preview": "[]",
        "capability_candidates_preview": "(none)",
        "external_candidates_preview": "(none)",
        "hub_matched_block": "",
        "cycle_id": "0001",
        "recent_history": "",
        "failed_capsules": [],
        "hub_lessons": [],
        "strategy_policy": None,
        "initial_user_prompt": None,
        "max_chars": 1_000_000,
    }
    defaults.update(overrides)
    return build_gep_prompt(**defaults)  # type: ignore[arg-type]


def test_gene_defaults() -> None:
    g = create_gene()
    assert g.type == "Gene"
    assert g.category == "innovate"
    assert g.constraints.max_files == 20
    assert ".git" in g.constraints.forbidden_paths


def test_gene_validates_required_fields() -> None:
    g = create_gene({"id": "gene_test", "category": "repair"})
    assert validate_gene(g) is True


def test_gene_rejects_missing_id() -> None:
    g = create_gene()
    with pytest.raises(ValueError, match="Gene.id is required"):
        validate_gene(g)


def test_gene_normalizes_invalid_category() -> None:
    g = create_gene({"category": "not_a_category"})
    assert g.category == "innovate"


def test_gene_accepts_explore_category() -> None:
    g = create_gene({"id": "g_explore", "category": "explore"})
    assert g.category == "explore"
    assert validate_gene(g) is True


def test_gene_accepts_optimize_category() -> None:
    g = create_gene({"id": "g_opt", "category": "optimize"})
    assert g.category == "optimize"


def test_gene_signals_match_default_empty() -> None:
    g = create_gene({"id": "g_sig"})
    assert g.signals_match == []


def test_capsule_defaults() -> None:
    c = create_capsule()
    assert c.type == "Capsule"
    assert c.outcome.status == "failed"
    assert c.blast_radius.files == 0


def test_capsule_rejects_missing_id() -> None:
    c = create_capsule()
    with pytest.raises(ValueError, match="Capsule.id is required"):
        validate_capsule(c)


def test_capsule_success_outcome() -> None:
    c = create_capsule({"id": "c1", "outcome": {"status": "success", "score": 1.0}})
    assert c.outcome.status == "success"
    assert validate_capsule(c) is True


def test_capsule_execution_trace_default() -> None:
    c = create_capsule({"id": "c_trace"})
    assert c.execution_trace == []


def test_task_defaults() -> None:
    t = create_task()
    assert t.type == "Task"
    assert t.status == "open"


def test_task_rejects_missing_id() -> None:
    t = create_task()
    with pytest.raises(ValueError, match="Task.task_id is required"):
        validate_task(t)


def test_task_with_id_validates() -> None:
    t = create_task({"task_id": "t1", "title": "do it"})
    assert validate_task(t) is True


def test_valid_categories_standard_quartet() -> None:
    assert VALID_CATEGORIES == ["repair", "optimize", "innovate", "explore"]
    assert "regulatory" not in VALID_CATEGORIES


def test_valid_categories_reexported_from_gene() -> None:
    assert VALID_CATEGORIES == gene_mod.VALID_CATEGORIES


def test_valid_outcome_statuses_reexported_from_capsule() -> None:
    assert VALID_OUTCOME_STATUSES == capsule_mod.VALID_OUTCOME_STATUSES
    assert VALID_OUTCOME_STATUSES == ["success", "failed"]


def test_valid_risk_levels() -> None:
    assert VALID_RISK_LEVELS == ["low", "medium", "high"]


def test_valid_trace_stages() -> None:
    assert VALID_TRACE_STAGES == ["build", "validate", "canary"]


def test_render_enum_pipe_joined() -> None:
    assert render_enum(VALID_CATEGORIES) == "repair|optimize|innovate|explore"
    assert render_enum(VALID_RISK_LEVELS) == "low|medium|high"
    assert render_enum(VALID_OUTCOME_STATUSES) == "success|failed"


def test_render_enum_list_quoted() -> None:
    assert render_enum_list(VALID_TRACE_STAGES) == '"build","validate","canary"'


def test_render_enum_empty() -> None:
    assert render_enum([]) == ""
    assert render_enum_list([]) == ""


def test_prompt_embeds_category_enum() -> None:
    prompt = _build_minimal_prompt()
    assert f'"{render_enum(VALID_CATEGORIES)}"' in prompt
    assert "repair|optimize|innovate|explore" in prompt


def test_prompt_embeds_risk_enum() -> None:
    assert f'"{render_enum(VALID_RISK_LEVELS)}"' in _build_minimal_prompt()


def test_prompt_embeds_outcome_enum() -> None:
    assert f'"{render_enum(VALID_OUTCOME_STATUSES)}"' in _build_minimal_prompt()


def test_prompt_embeds_trace_stages() -> None:
    assert f"{{{render_enum_list(VALID_TRACE_STAGES)}}}" in _build_minimal_prompt()


def test_prompt_omits_regulatory_category() -> None:
    assert "regulatory" not in _build_minimal_prompt()


def test_prompt_source_no_hardcoded_category_triplet() -> None:
    src = Path(__file__).resolve().parents[1] / "src" / "evolver" / "gep" / "prompt.py"
    text = src.read_text(encoding="utf-8")
    assert '"repair|optimize|innovate"' not in text
    assert "'repair|optimize|innovate'" not in text
    assert '"repair|optimize|innovate|explore"' not in text
    assert "'repair|optimize|innovate|explore'" not in text
    assert "render_enum(VALID_CATEGORIES)" in text


def test_prompt_source_uses_protocol_enums() -> None:
    src = Path(__file__).resolve().parents[1] / "src" / "evolver" / "gep" / "prompt.py"
    text = src.read_text(encoding="utf-8")
    assert "VALID_RISK_LEVELS" in text
    assert "VALID_OUTCOME_STATUSES" in text
    assert "VALID_TRACE_STAGES" in text


def test_schemas_package_exports_render_helpers() -> None:
    from evolver.gep import schemas

    assert hasattr(schemas, "render_enum")
    assert hasattr(schemas, "render_enum_list")
    assert hasattr(schemas, "VALID_RISK_LEVELS")
    assert hasattr(schemas, "VALID_TRACE_STAGES")


def test_gene_all_valid_categories_roundtrip() -> None:
    for cat in VALID_CATEGORIES:
        g = create_gene({"id": f"g_{cat}", "category": cat})
        assert g.category == cat
        assert validate_gene(g) is True
