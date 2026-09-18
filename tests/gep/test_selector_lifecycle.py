"""Selector enforcement of gene lifecycle + applicability (RSI P1-5)."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.gep.selector import select_gene, select_gene_and_capsule


def _gene(gene_id: str, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": gene_id,
        "category": "repair",
        "signals_match": ["log_error"],
    }
    payload.update(extra)
    return payload


class TestRetiredFilter:
    def test_retired_excluded_even_as_best_match(self) -> None:
        picked = select_gene(
            [_gene("g_dead"), _gene("g_live")],
            ["log_error"],
            {"retiredGeneIds": {"g_dead"}},
        )
        assert picked["selected"] is not None
        assert picked["selected"]["id"] == "g_live"

    def test_retired_only_pool_selects_nothing(self) -> None:
        picked = select_gene([_gene("g_dead")], ["log_error"], {"retiredGeneIds": {"g_dead"}})
        assert picked["selected"] is None

    def test_retired_distilled_fallback_is_skipped(self) -> None:
        distilled = {"id": "gene_distilled_x", "category": "repair", "signals_match": ["zzz"]}
        # Without lifecycle the distilled fallback rescues the empty candidate set.
        rescued = select_gene([dict(distilled)], ["log_error"], {})
        assert rescued["selected"] is not None
        # Retired: the fallback must not resurrect it.
        blocked = select_gene(
            [dict(distilled)], ["log_error"], {"retiredGeneIds": {"gene_distilled_x"}}
        )
        assert blocked["selected"] is None


class TestReviewPenalty:
    def test_under_review_loses_tie_to_active(self) -> None:
        picked = select_gene(
            [_gene("g_review"), _gene("g_active")],
            ["log_error"],
            {"underReviewGeneIds": {"g_review"}},
        )
        assert picked["selected"] is not None
        assert picked["selected"]["id"] == "g_active"

    def test_under_review_sole_match_still_selectable(self) -> None:
        picked = select_gene(
            [_gene("g_review")], ["log_error"], {"underReviewGeneIds": {"g_review"}}
        )
        assert picked["selected"] is not None
        assert picked["selected"]["id"] == "g_review"
        assert picked["score"] == 0.5


class TestApplicabilityGate:
    def test_declared_families_hard_gate_retrieval(self) -> None:
        scoped = _gene("g_scoped", applicability={"signal_families": ["mypy_error"]})
        assert select_gene([scoped], ["log_error"])["selected"] is None

    def test_matching_family_passes_gate(self) -> None:
        scoped = _gene(
            "g_scoped",
            signals_match=["log_error", "mypy_error"],
            applicability={"signal_families": ["mypy_error"]},
        )
        picked = select_gene([scoped], ["mypy_error"])
        assert picked["selected"] is not None
        assert picked["selected"]["id"] == "g_scoped"

    def test_pipe_alias_family_matches(self) -> None:
        scoped = _gene(
            "g_alias",
            signals_match=["log_error", "type_error"],
            applicability={"signal_families": ["mypy_error|type_error"]},
        )
        assert select_gene([scoped], ["type_error"])["selected"] is not None

    def test_absent_applicability_is_unaffected(self) -> None:
        picked = select_gene([_gene("g_plain")], ["log_error"])
        assert picked["selected"] is not None


class TestPipelineWiring:
    def test_pipeline_loads_lifecycle_sets_from_disk(self, temp_workspace: Path) -> None:
        from evolver.gep import gene_lifecycle as gl

        state = {
            "version": 1,
            "genes": {
                "g_dead": gl.GeneLifecycleRecord(gene_id="g_dead", status="retired").model_dump()
            },
        }
        path = gl.lifecycle_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")

        ctx = {
            "genes": [_gene("g_dead"), _gene("g_live")],
            "capsules": [],
            "signals": ["log_error"],
            "memoryAdvice": {},
        }
        result = select_gene_and_capsule(ctx)
        assert result["selectedGene"] is not None
        assert result["selectedGene"]["id"] == "g_live"

    def test_corrupt_lifecycle_file_does_not_break_selection(self, temp_workspace: Path) -> None:
        from evolver.gep import gene_lifecycle as gl

        path = gl.lifecycle_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")
        ctx = {"genes": [_gene("g_live")], "capsules": [], "signals": ["log_error"]}
        result = select_gene_and_capsule(ctx)
        assert result["selectedGene"] is not None
        assert result["selectedGene"]["id"] == "g_live"
