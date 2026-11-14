"""Sprint 24.9: selector geneStats augmented by event-log projection."""

from __future__ import annotations

from pathlib import Path

from evolver.gep.event_projection import augment_gene_stats


def _evt(run_id: str, gene_id: str, status: str, score: float = 1.0) -> dict[str, object]:
    return {
        "type": "EvolutionEvent",
        "id": f"evt_{run_id}",
        "run_id": run_id,
        "timestamp": "2026-08-24T00:00:00Z",
        "gene_id": gene_id,
        "outcome": {"status": status, "score": score},
    }


class TestAugmentGeneStats:
    def test_fills_cold_start_genes(self, temp_workspace: Path) -> None:
        from evolver.gep.asset_store import append_event_jsonl

        append_event_jsonl(_evt("r1", "gene_known", "success"))
        append_event_jsonl(_evt("r2", "gene_global_only", "failed", score=0.0))
        append_event_jsonl(_evt("r3", "gene_global_only", "success"))

        merged = augment_gene_stats({"gene_known": {"attempts": 5.0, "successes": 4.0}})

        # Niche stats keep precedence.
        assert merged["gene_known"]["attempts"] == 5.0
        # Cold-start gene gets global replay tallies.
        assert merged["gene_global_only"] == {
            "attempts": 2.0,
            "successes": 1.0,
            "failures": 1.0,
        }

    def test_empty_projection_returns_input(self, temp_workspace: Path) -> None:
        original = {"gene_a": {"attempts": 1.0, "successes": 1.0}}
        assert augment_gene_stats(original) == original


class TestComparisonThesisIntegration:
    def test_run_comparison_includes_thesis(self) -> None:
        from evolver.experiment.comparison import run_comparison

        tasks = [{"id": f"t{i}", "prompt": f"task {i}"} for i in range(40)]

        def agent_fn(prompt: str, genes: list[dict[str, object]] | None) -> str:
            return "solved"

        results = run_comparison(tasks, agent_fn=agent_fn)
        thesis = results["thesis"]
        assert thesis["verdict"] in (
            "evolved_better",
            "no_clear_improvement",
            "worse",
            "insufficient_samples",
        )
        assert isinstance(thesis["ci95"], list)
        assert results["baseline_metrics"]["total"] == len(tasks)
        assert results["evolved_metrics"]["total"] == len(tasks)
