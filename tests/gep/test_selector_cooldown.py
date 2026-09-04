"""Dogfood round-5: applied-gene cooldown in the selector.

Ticks kept re-dispatching genes whose mutation had already solidified rounds
earlier (same signals still in the corpus, same gene still the top match) —
each re-dispatch wastes a cycle. Recent successful genes now take a score
penalty (not a ban): fresher candidates win ties, but a sole matching gene
stays selectable.
"""

from __future__ import annotations

from typing import Any

import pytest

from evolver.gep import selector


def _gene(gid: str, signals: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": gid,
        "category": "repair",
        "signals_match": signals or ["hub_offline"],
        "summary": "fix hub friction",
        "learning_history": [],
        "anti_patterns": [],
    }


def _event(gene_id: str | None, status: str = "success") -> dict[str, Any]:
    mutation = {"gene_id": gene_id} if gene_id else {}
    return {"id": f"evt_{gene_id}", "mutation": mutation, "outcome": {"status": status}}


class TestAppliedCooldownIds:
    def test_success_events_yield_ids(self) -> None:
        ids = selector._applied_cooldown_ids([_event("g_applied"), _event(None)])
        assert ids == {"g_applied"}

    def test_failed_outcomes_do_not_cool(self) -> None:
        assert selector._applied_cooldown_ids([_event("g_fail", status="failed")]) == set()

    def test_window_truncates_old_successes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("evolver.config.APPLIED_GENE_COOLDOWN_EVENTS", 1)
        events = [_event("g_old"), _event("g_recent")]
        assert selector._applied_cooldown_ids(events) == {"g_recent"}

    def test_noise_events_do_not_dilute_window(self) -> None:
        # Bookkeeping stubs (no mutation/outcome) must not consume window slots.
        noise: list[dict[str, Any]] = [{"id": "x1", "timestamp": "t1"}] * 10
        events = [*noise, _event("g_applied"), noise[0]]
        assert selector._applied_cooldown_ids(events) == {"g_applied"}


class TestCooldownPenalty:
    def test_penalized_gene_loses_to_fresher_match(self) -> None:
        genes = [_gene("g_applied"), _gene("g_fresh")]
        picked = selector.select_gene(
            genes,
            ["hub_offline"],
            {"bannedGeneIds": set(), "appliedCooldownIds": {"g_applied"}},
        )
        assert picked["selected"]["id"] == "g_fresh"

    def test_sole_matching_gene_still_selectable(self) -> None:
        picked = selector.select_gene(
            [_gene("g_applied")],
            ["hub_offline"],
            {"bannedGeneIds": set(), "appliedCooldownIds": {"g_applied"}},
        )
        assert picked["selected"]["id"] == "g_applied"

    def test_no_events_no_behavior_change(self) -> None:
        picked = selector.select_gene(
            [_gene("g1"), _gene("g2")],
            ["hub_offline"],
            {"bannedGeneIds": set()},
        )
        assert picked["selected"]["id"] == "g1"

    def test_end_to_end_through_select_gene_and_capsule(self) -> None:
        result = selector.select_gene_and_capsule(
            {
                "genes": [_gene("gene_landed"), _gene("gene_new")],
                "capsules": [],
                "signals": ["hub_offline"],
                "memoryAdvice": {},
                "recentEvents": [_event("gene_landed")],
            }
        )
        assert result["selectedGene"]["id"] == "gene_new"
