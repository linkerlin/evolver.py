"""Tests for the GEP prompt's evidence blocks (经验即证据 §5.2).

Order is the contract: the previous round's record (engine-side) precedes
the evidence pack (result-side), and the clue block (host-reported, weakest)
comes last — separate, never merged, counted apart.
"""

from __future__ import annotations

from evolver.gep.prompt import build_gep_prompt


def _prompt(**overrides: object) -> str:
    kwargs: dict[str, object] = {
        "now_iso": "2026-10-02T00:00:00Z",
        "context": "",
        "signals": [],
        "selector": {"selectedBy": "test"},
        "parent_event_id": None,
        "selected_gene": None,
        "capsule_candidates": "(none)",
        "genes_preview": "[]",
        "capsules_preview": "[]",
        "capability_candidates_preview": "(none)",
        "external_candidates_preview": "(none)",
        "hub_matched_block": "{}",
        "cycle_id": "c1",
        "recent_history": "",
        "failed_capsules": [],
        "hub_lessons": [],
        "strategy_policy": None,
        "initial_user_prompt": None,
    }
    kwargs.update(overrides)
    return build_gep_prompt(**kwargs)  # type: ignore[arg-type]


def test_episode_block_precedes_evidence_pack_and_clue_block_stays_separate() -> None:
    prompt = _prompt(
        evidence_pack="## Evidence Pack\nEVIDENCE-PACK-CONTENT",
        episode_block="## Previous Episode\nEPISODE-BLOCK-CONTENT",
        clue_block="## Host Clues\nCLUE-BLOCK-CONTENT",
    )
    assert prompt.index("EPISODE-BLOCK-CONTENT") < prompt.index("EVIDENCE-PACK-CONTENT")
    assert prompt.index("EVIDENCE-PACK-CONTENT") < prompt.index("CLUE-BLOCK-CONTENT")
    # not merged: each block keeps its own heading, counted apart
    assert "## Previous Episode" in prompt
    assert "## Evidence Pack" in prompt
    assert "## Host Clues" in prompt


def test_evidence_pack_still_renders_without_an_episode_block() -> None:
    prompt = _prompt(evidence_pack="EVIDENCE-PACK-CONTENT")
    assert "EVIDENCE-PACK-CONTENT" in prompt
    assert "EPISODE-BLOCK-CONTENT" not in prompt
    assert "CLUE-BLOCK-CONTENT" not in prompt
