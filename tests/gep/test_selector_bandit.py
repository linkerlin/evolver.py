"""Sprint 22.3: UCB1 bandit parent sampling in the gene selector.

Closes the argmax lock-in gap (演进方案.md §13.2-#3) — every non-banned
candidate keeps a non-zero selection probability; --review stays deterministic.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from evolver.gep import selector


def _gene(gid: str, score_signals: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": gid,
        "category": "repair",
        "signals_match": score_signals or ["log_error"],
        "summary": "fix errors",
        "learning_history": [],
        "anti_patterns": [],
    }


def _call_select_gene(bandit: bool = False, gene_stats: dict[str, Any] | None = None) -> Any:
    genes = [_gene("g1"), _gene("g2"), _gene("g3")]
    return selector.select_gene(
        genes,
        ["log_error"],
        {
            "bannedGeneIds": set(),
            "bandit": bandit,
            "geneStats": gene_stats or {},
        },
    )


class TestUcb1Weight:
    def test_untried_genes_get_max_exploration(self) -> None:
        untried = selector._ucb1_weight(score=1.0, attempts=0, successes=0, total_attempts=10)
        tried = selector._ucb1_weight(score=1.0, attempts=10, successes=9, total_attempts=10)
        assert untried > tried

    def test_success_rate_boosts_tried_gene(self) -> None:
        good = selector._ucb1_weight(score=1.0, attempts=10, successes=9, total_attempts=20)
        bad = selector._ucb1_weight(score=1.0, attempts=10, successes=1, total_attempts=20)
        assert good > bad

    def test_zero_score_is_zero_weight(self) -> None:
        w = selector._ucb1_weight(score=0.0, attempts=5, successes=5, total_attempts=5)
        assert w == 0.0

    def test_more_attempts_shrink_confidence_term(self) -> None:
        a = selector._ucb1_weight(score=1.0, attempts=2, successes=1, total_attempts=20)
        b = selector._ucb1_weight(score=1.0, attempts=20, successes=10, total_attempts=20)
        # mean equal; sqrt(ln N / n) shrinks with n
        assert math.isclose(
            a - b, 1.0 * (1.0 + math.sqrt(math.log(20) / 2)) - (1.0 + math.sqrt(math.log(20) / 20))
        )


class TestBanditSelection:
    def test_disabled_keeps_argmax(self) -> None:
        result = _call_select_gene(bandit=False)
        assert result["selected"]["id"] == "g1"
        assert result["driftMode"] == "score_ranked"

    def test_bandit_samples_from_weights(self, monkeypatch: pytest.MonkeyPatch) -> None:
        candidates_capture: dict[str, Any] = {}

        def fake_choices(population: list[Any], weights: list[float], k: int) -> list[Any]:
            candidates_capture["weights"] = weights
            return [population[1]]  # force g2

        monkeypatch.setattr(selector.random, "choices", fake_choices)
        result = _call_select_gene(
            bandit=True,
            gene_stats={
                "g1": {"attempts": 10, "successes": 9},
                "g2": {"attempts": 1, "successes": 0},
                "g3": {"attempts": 0, "successes": 0},
            },
        )
        assert result["selected"]["id"] == "g2"
        assert result["driftMode"] == "ucb1_sample"
        assert len(candidates_capture["weights"]) == 3
        # alternatives exclude the selected gene
        assert all(a["id"] != "g2" for a in result["alternatives"])
        assert len(result["alternatives"]) == 2

    def test_bandit_untried_gene_can_win(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_choices(population: list[Any], weights: list[float], k: int) -> list[Any]:
            return [population[2]]  # g3 (never tried)

        monkeypatch.setattr(selector.random, "choices", fake_choices)
        result = _call_select_gene(
            bandit=True,
            gene_stats={
                "g1": {"attempts": 10, "successes": 9},
                "g2": {"attempts": 10, "successes": 9},
                "g3": {"attempts": 0, "successes": 0},
            },
        )
        assert result["selected"]["id"] == "g3"


class TestSelectGeneAndCapsuleBandit:
    def _ctx(self, **overrides: Any) -> dict[str, Any]:
        ctx: dict[str, Any] = {
            "genes": [_gene("g1"), _gene("g2")],
            "capsules": [],
            "signals": ["log_error"],
            "memoryAdvice": {},
            "driftEnabled": False,
        }
        ctx.update(overrides)
        return ctx

    def test_flag_on_enables_bandit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_BANDIT_SELECTION", "true")
        seen: dict[str, Any] = {}

        def fake_choices(population: list[Any], weights: list[float], k: int) -> list[Any]:
            seen["weights"] = weights
            return [population[0]]

        monkeypatch.setattr(selector.random, "choices", fake_choices)
        result = selector.select_gene_and_capsule(self._ctx())
        assert result["selectionPath"] == "ucb1_sample"
        assert seen["weights"]

    def test_review_mode_forces_deterministic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_BANDIT_SELECTION", "true")
        calls: list[Any] = []
        monkeypatch.setattr(
            selector.random, "choices", lambda population, weights, k: calls.append(1) or []
        )
        result = selector.select_gene_and_capsule(self._ctx(IS_REVIEW_MODE=True))
        assert result["selectionPath"] == "score_ranked"
        assert calls == []

    def test_flag_off_keeps_argmax(self) -> None:
        result = selector.select_gene_and_capsule(self._ctx())
        assert result["selectionPath"] == "score_ranked"


class TestReviewModeThreading:
    def test_build_initial_context_threads_review(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(selector.random, "choices", lambda *a, **k: [])
        from evolver.evolve.runner import _build_initial_context

        ctx = _build_initial_context(review_mode=True)
        assert ctx["IS_REVIEW_MODE"] is True
        assert _build_initial_context(review_mode=False)["IS_REVIEW_MODE"] is False
