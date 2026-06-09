"""Tests for evolver.gep.prompt — equivalent to evolver/test/prompt.test.js."""

from __future__ import annotations

from evolver.gep.prompt import build_gep_prompt, compact_preview_for_prompt


def _build_minimal(**overrides):
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
    }
    defaults.update(overrides)
    return build_gep_prompt(**defaults)


def test_prompt_no_inline_status_write() -> None:
    p = _build_minimal()
    assert "mkdirSync" not in p
    assert "writeFileSync" not in p
    assert "status_" not in p


def test_prompt_no_post_solidify() -> None:
    p = _build_minimal()
    assert "POST-SOLIDIFY" not in p
    assert "Wrapper Authority" not in p


def test_prompt_has_gep_header() -> None:
    p = _build_minimal()
    assert "GEP" in p
    assert "GENOME EVOLUTION PROTOCOL" in p


def test_prompt_has_mandatory_schemas() -> None:
    p = _build_minimal()
    assert "Mutation" in p
    assert "PersonalityState" in p
    assert "EvolutionEvent" in p
    assert "Gene" in p
    assert "Capsule" in p


def test_prompt_has_ethics() -> None:
    p = _build_minimal()
    assert "CONSTITUTIONAL ETHICS" in p
    assert "HUMAN WELFARE" in p


def test_compact_preview_strips_bloated_fields() -> None:
    heavy = "a" * 100
    raw = '[{"type": "Capsule", "id": "c1", "summary": "s", "diff": "' + heavy + '"}]'
    compacted = compact_preview_for_prompt(raw)
    assert heavy not in compacted
    assert '"id": "c1"' in compacted


def test_compact_preview_preserves_fences() -> None:
    heavy = "a" * 100
    data = [{"type": "Capsule", "id": "cap_prod", "summary": "s", "diff": heavy}]
    fenced = "```json\n" + __import__("json").dumps(data, indent=2) + "\n```"
    compacted = compact_preview_for_prompt(fenced)
    assert heavy not in compacted
    assert compacted.startswith("```json")
    assert compacted.endswith("```")
