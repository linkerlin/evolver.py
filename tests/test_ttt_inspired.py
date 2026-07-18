"""TTT-inspired behaviour (Node test/tttInspired.test.js contract)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep import memory_graph as mg
from evolver.gep.prompt import build_inplace_gep_prompt
from evolver.gep.selector import (
    INPLACE_BLAST_MAX_FILES,
    INPLACE_BLAST_MAX_LINES,
    is_inplace_gene,
    select_gene,
    select_multi_gene_chunk,
)
from evolver.gep.ttt_inspired import compute_predictive_boost


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evomap"))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("MEMORY_GRAPH_PATH", str(tmp_path / "memory_graph.jsonl"))
    return tmp_path


# -- Phase 1: Predictive Outcome ------------------------------------------------


class TestComputePredictiveBoost:
    def test_positive_boost_for_actionable_signals(self) -> None:
        result = compute_predictive_boost(
            baseline_observed={"signal_count": 3},
            current_observed={},
            signals=["log_error", "perf_bottleneck", "capability_gap"],
        )
        assert result["boost"] > 0
        assert result["signal_clarity"] > 0
        assert result["frontier_touched"] is False

    def test_frontier_touched_for_curriculum_signals(self) -> None:
        result = compute_predictive_boost(
            baseline_observed={},
            current_observed={},
            signals=["curriculum_target:frontier:some_key", "log_error"],
        )
        assert result["frontier_touched"] is True
        assert result["boost"] > 0

    def test_empty_signals_near_zero(self) -> None:
        result = compute_predictive_boost(
            baseline_observed=None,
            current_observed=None,
            signals=[],
        )
        assert isinstance(result["boost"], float)
        assert -0.1 <= result["boost"] <= 0.1

    def test_decorative_reduces_clarity(self) -> None:
        all_decorative = compute_predictive_boost(
            signals=["stable_success_plateau", "memory_missing"]
        )
        mixed = compute_predictive_boost(signals=["stable_success_plateau", "log_error"])
        assert mixed["signal_clarity"] > all_decorative["signal_clarity"]


class TestInferOutcomeEnhanced:
    def test_record_outcome_includes_predictive(self, isolated: Path) -> None:
        mg.record_attempt(
            signals=["log_error"],
            selected_gene={"id": "gene_test", "category": "repair"},
            drift_enabled=False,
        )
        ev = mg.record_outcome_from_state(
            signals=["stable_no_error"],
            observations={},
        )
        assert ev is not None
        assert ev["kind"] == "outcome"
        pred = (ev.get("outcome") or {}).get("predictive")
        assert isinstance(pred, dict)
        assert isinstance(pred.get("signal_clarity"), (int, float))
        assert isinstance(pred.get("frontier_touched"), bool)


# -- Phase 2: In-Place Gene -----------------------------------------------------


class TestIsInplaceGene:
    def test_true_for_inplace_mode(self) -> None:
        assert is_inplace_gene({"execution_mode": "inplace"}) is True

    def test_false_for_regular(self) -> None:
        assert is_inplace_gene({"type": "Gene", "id": "gene_x"}) is False

    def test_falsy_for_none(self) -> None:
        assert not is_inplace_gene(None)


class TestInplacePreference:
    GENES = [
        {
            "type": "Gene",
            "id": "gene_full",
            "category": "repair",
            "signals_match": ["error", "failed"],
            "strategy": ["full fix"],
        },
        {
            "type": "Gene",
            "id": "gene_inplace",
            "category": "optimize",
            "execution_mode": "inplace",
            "signals_match": ["error", "timeout"],
            "strategy": ["adjust timeout"],
        },
    ]

    def test_prefers_inplace_when_flag_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("evolver.gep.selector.random.random", lambda: 0.99)
        result = select_gene(self.GENES, ["error", "timeout"], {"preferInplace": True})
        assert result["selected"] is not None
        assert result["selected"]["id"] == "gene_inplace"

    def test_no_force_when_flag_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("evolver.gep.selector.random.random", lambda: 0.99)
        result = select_gene(self.GENES, ["error", "failed"], {"preferInplace": False})
        assert result["selected"] is not None
        assert result["selected"]["id"] == "gene_full"


class TestBuildInplacePrompt:
    def test_header_and_limits(self) -> None:
        prompt = build_inplace_gep_prompt(
            now_iso="2026-07-19T00:00:00Z",
            signals=["timeout_error"],
            selected_gene={
                "id": "gene_timeout_tune",
                "strategy": ["Increase timeout to 30s"],
            },
            parent_event_id="evt_123",
            cycle_id="42",
        )
        assert "IN-PLACE MODE" in prompt
        assert "PARAMETER-ONLY" in prompt
        assert "gene_timeout_tune" in prompt
        assert "max 5 files" in prompt

    def test_missing_strategy(self) -> None:
        prompt = build_inplace_gep_prompt(
            signals=["error"],
            selected_gene={"id": "gene_x"},
        )
        assert "IN-PLACE MODE" in prompt
        assert "Identify parameter" in prompt


class TestInplaceConstants:
    def test_blast_radius(self) -> None:
        assert INPLACE_BLAST_MAX_FILES == 5
        assert INPLACE_BLAST_MAX_LINES == 100


# -- Phase 3: Multi-Gene Chunk --------------------------------------------------


class TestSelectMultiGeneChunk:
    GENES = [
        {
            "type": "Gene",
            "id": "gene_error_fix",
            "category": "repair",
            "signals_match": ["error", "exception", "failed"],
        },
        {
            "type": "Gene",
            "id": "gene_perf",
            "category": "optimize",
            "signals_match": ["latency", "throughput", "slow"],
        },
        {
            "type": "Gene",
            "id": "gene_error_alt",
            "category": "repair",
            "signals_match": ["error", "crash", "failed"],
        },
        {
            "type": "Gene",
            "id": "gene_innovate",
            "category": "innovate",
            "signals_match": ["capability_gap", "feature_request"],
        },
    ]

    def test_single_match(self) -> None:
        result = select_multi_gene_chunk(
            genes=self.GENES,
            signals=["capability_gap"],
            memory_advice={
                "bannedGeneIds": set(),
                "preferredGeneId": None,
                "totalAttempts": 0,
            },
            drift_enabled=False,
        )
        assert len(result["genes"]) >= 1
        assert result["genes"][0]["id"] == "gene_innovate"

    def test_multiple_non_conflicting(self) -> None:
        result = select_multi_gene_chunk(
            genes=self.GENES,
            signals=["error", "latency", "capability_gap"],
            memory_advice={
                "bannedGeneIds": set(),
                "preferredGeneId": None,
                "totalAttempts": 0,
            },
            drift_enabled=False,
        )
        assert len(result["genes"]) >= 2
        ids = {g["id"] for g in result["genes"]}
        # Conflicting repair pair should not both be present
        assert not ({"gene_error_alt", "gene_error_fix"} <= ids)

    def test_empty_when_no_match(self) -> None:
        result = select_multi_gene_chunk(
            genes=self.GENES,
            signals=["completely_unknown_signal"],
            memory_advice=None,
            drift_enabled=False,
        )
        assert result["genes"] == []


# -- Phase 4: Epoch Boundary ----------------------------------------------------


class TestEpochBoundary:
    def test_reset_on_streak_signal(self, isolated: Path) -> None:
        result = mg.check_epoch_boundary(
            signals=["consecutive_failure_streak_5", "log_error"],
            current_env_fingerprint_key="abc123",
            current_gene_lib_version="glib_v1",
        )
        assert result["shouldReset"] is True
        assert "consecutive_failure_streak_5" in result["reason"]

    def test_reset_on_failure_loop(self, isolated: Path) -> None:
        result = mg.check_epoch_boundary(
            signals=["failure_loop_detected"],
            current_env_fingerprint_key="abc123",
            current_gene_lib_version="glib_v1",
        )
        assert result["shouldReset"] is True

    def test_no_reset_for_normal(self, isolated: Path) -> None:
        result = mg.check_epoch_boundary(
            signals=["log_error", "perf_bottleneck"],
            current_env_fingerprint_key=None,
            current_gene_lib_version=None,
        )
        assert result["shouldReset"] is False


class TestResetMemoryPreferences:
    def test_writes_epoch_event_and_state(self, isolated: Path) -> None:
        result = mg.reset_memory_preferences(
            reason="env_major_change",
            current_env_fingerprint_key="new_env_key",
            current_gene_lib_version="glib_v2",
        )
        assert result["epochId"]
        assert result["reason"] == "env_major_change"

        graph = Path(isolated / "memory_graph.jsonl")
        # MEMORY_GRAPH_PATH may be set; use mg path
        from evolver.gep.paths import get_memory_graph_path

        path = get_memory_graph_path()
        if not path.exists():
            path = graph
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        epoch_ev = json.loads(lines[-1])
        assert epoch_ev["kind"] == "epoch_boundary"
        assert epoch_ev["epoch"]["id"] == result["epochId"]

        epoch = mg.read_current_epoch()
        assert epoch["epoch_id"] == result["epochId"]
        assert epoch["prev_env_fingerprint_key"] == "new_env_key"


class TestMemoryAdviceAfterEpoch:
    def test_deprioritizes_pre_epoch_outcomes(self, isolated: Path) -> None:
        mg.record_attempt(
            signals=["error_a"],
            selected_gene={"id": "gene_old", "category": "repair"},
        )
        mg.record_outcome_from_state(signals=["stable_no_error"], observations={})

        # Explicit preference for old gene
        mg.record_signal_gene_preference(
            gene_id="gene_old", signals=["error_a"], source="solidify_success"
        )

        mg.reset_memory_preferences(
            reason="env_major_change",
            current_env_fingerprint_key="new_key",
        )

        mg.record_attempt(
            signals=["error_a"],
            selected_gene={"id": "gene_new", "category": "repair"},
        )
        mg.record_outcome_from_state(signals=["stable_no_error"], observations={})
        mg.record_signal_gene_preference(
            gene_id="gene_new", signals=["error_a"], source="solidify_success"
        )

        advice = mg.get_memory_advice(
            signals=["error_a"],
            genes=[
                {"id": "gene_old", "type": "Gene"},
                {"id": "gene_new", "type": "Gene"},
            ],
            drift_enabled=False,
        )
        # After reset, preferred should be gene_new (post-epoch) or None — not gene_old alone
        assert advice["preferredGeneId"] in ("gene_new", None)
        if advice["preferredGeneId"] is None:
            # Acceptable if scoring has no preference; must not lock to pre-epoch only
            prefs = mg.read_current_epoch()
            assert prefs.get("epoch_id")
