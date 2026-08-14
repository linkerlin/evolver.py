"""Sprint 22.4: niche archive — top-k preferred genes + 30-day ban probation.

Covers the MAP-Elites/AlphaEvolve resurface gap (演进方案.md §13.2-#5).
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from evolver.gep import memory_graph


def _seed_outcomes(
    counts: dict[str, tuple[int, int]],
    signals: list[str] | None = None,
) -> None:
    """``{gene_id: (successes, failures)}`` on the same signal key."""
    signals = signals or ["log_error"]
    for gid, (succ, fail) in counts.items():
        for _ in range(succ):
            memory_graph.record_outcome(
                signals=signals,
                selected_gene={"id": gid},
                outcome={"status": "success", "score": 1.0},
            )
        for _ in range(fail):
            memory_graph.record_outcome(
                signals=signals,
                selected_gene={"id": gid},
                outcome={"status": "failed", "error": "x"},
            )


def _advice(
    monkeypatch: pytest.MonkeyPatch,
    genes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return memory_graph.get_memory_advice(
        signals=["log_error"],
        genes=genes or [],
    )


class TestBanProbation:
    @pytest.mark.usefixtures("temp_workspace")
    def test_flag_off_keeps_permanent_ban(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_outcomes({"g_bad": (0, 4)})  # 100% failure, >= 3 attempts
        advice = _advice(monkeypatch)
        assert "g_bad" in advice["bannedGeneIds"]
        assert (
            memory_graph._probation_until(memory_graph.compute_signal_key(["log_error"]), "g_bad")
            is None
        )

    @pytest.mark.usefixtures("temp_workspace")
    def test_flag_on_probates_ban(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_NICHE_TOPK", "true")
        _seed_outcomes({"g_bad": (0, 4)})
        key = memory_graph.compute_signal_key(["log_error"])
        # First advice call: 30-day sentence starts — the gene is banned and
        # the probation deadline is persisted.
        advice = _advice(monkeypatch)
        assert "g_bad" in advice["bannedGeneIds"]
        until = memory_graph._probation_until(key, "g_bad")
        assert until is not None
        assert until > time.time() + 29 * 86400  # ~30 days out
        # Second call (same day): probation is running -> selectable again.
        advice = _advice(monkeypatch)
        assert "g_bad" not in advice["bannedGeneIds"]

    @pytest.mark.usefixtures("temp_workspace")
    def test_expired_probation_rebans(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_NICHE_TOPK", "true")
        _seed_outcomes({"g_bad": (0, 4)})
        key = memory_graph.compute_signal_key(["log_error"])
        state = memory_graph._read_state()
        state.setdefault("probation_by_signal", {})[key] = {"g_bad": time.time() - 1}
        memory_graph._write_state(state)
        advice = _advice(monkeypatch)
        assert "g_bad" in advice["bannedGeneIds"]
        # new probation window persisted
        assert memory_graph._probation_until(key, "g_bad") > time.time() + 29 * 86400


class TestTopKPreferred:
    @pytest.mark.usefixtures("temp_workspace")
    def test_top_three_by_rate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_NICHE_TOPK", "true")
        _seed_outcomes(
            {
                "g_a": (5, 0),  # 1.0
                "g_b": (3, 1),  # 0.75
                "g_c": (2, 2),  # 0.5, not banned (0.5 < 0.8)
                "g_d": (1, 9),  # 0.1
            }
        )
        advice = _advice(monkeypatch)
        assert advice["preferredGeneIds"] == ["g_a", "g_b", "g_c"]

    @pytest.mark.usefixtures("temp_workspace")
    def test_banned_gene_excluded_from_topk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_NICHE_TOPK", "true")
        _seed_outcomes(
            {
                "g_a": (5, 0),
                "g_b": (1, 4),  # 80% failure -> banned, excluded
            }
        )
        advice = _advice(monkeypatch)
        assert advice["preferredGeneIds"] == ["g_a"]

    @pytest.mark.usefixtures("temp_workspace")
    def test_flag_off_no_topk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_outcomes({"g_a": (5, 0), "g_b": (3, 1)})
        advice = _advice(monkeypatch)
        assert advice["preferredGeneIds"] == []

    @pytest.mark.usefixtures("temp_workspace")
    def test_solidify_preference_anchors_topk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_NICHE_TOPK", "true")
        _seed_outcomes(
            {
                "g_a": (5, 0),  # 1.0
                "g_b": (3, 1),  # 0.75
                "g_d": (2, 2),  # 0.5
                "g_c": (1, 3),  # 0.25, 4th by rate, not banned
            }
        )
        memory_graph.record_signal_gene_preference(
            gene_id="g_c", signals=["log_error"], source="solidify_success"
        )
        advice = _advice(monkeypatch)
        # solidify success anchors the niche top-k at position 0
        assert advice["preferredGeneIds"][0] == "g_c"
        assert set(advice["preferredGeneIds"]) == {"g_c", "g_a", "g_b"}


class TestSelectorTopKBoost:
    def test_preferred_gene_ids_all_boosted(self) -> None:
        from evolver.gep import selector

        genes = [
            {"id": "g1", "signals_match": ["log_error"], "summary": "a"},
            {"id": "g2", "signals_match": ["log_error"], "summary": "b"},
            {"id": "g3", "signals_match": ["log_error"], "summary": "c"},
        ]
        result = selector.select_gene(
            genes,
            ["log_error"],
            {"bannedGeneIds": set(), "preferredGeneIds": ["g2", "g3"]},
        )
        # g2/g3 got the 1.5x boost over g1 — either may win, but g1 cannot
        assert result["selected"]["id"] in ("g2", "g3")

    def test_legacy_single_preferred_still_works(self) -> None:
        from evolver.gep import selector

        genes = [
            {"id": "g1", "signals_match": ["log_error"], "summary": "a"},
            {"id": "g2", "signals_match": ["log_error"], "summary": "b"},
        ]
        result = selector.select_gene(
            genes,
            ["log_error"],
            {"bannedGeneIds": set(), "preferredGeneId": "g2"},
        )
        assert result["selected"]["id"] == "g2"
