"""Experiment comparison — orchestrate multi-configuration A/B experiments.

Equivalent to ``evolver/src/experiment/comparison.js``.

Runs a set of tasks under two configurations (baseline vs evolved),
collects results, and produces a comparison report.
"""

from __future__ import annotations

from typing import Any

from evolver.experiment.agent_runner import run_task
from evolver.experiment.metrics import compare_metrics, compute_metrics, format_report


def run_comparison(
    tasks: list[dict[str, Any]],
    *,
    genes: list[dict[str, Any]] | None = None,
    agent_fn: Any | None = None,
) -> dict[str, Any]:
    """Run an A/B comparison: baseline vs evolved on the same tasks.

    Parameters:
        tasks: List of task dicts (each with ``id``, ``prompt``, optional ``expected``).
        genes: Gene dicts to inject for the evolved configuration.
        agent_fn: Agent callable (same for both configs; genes provide the difference).

    Returns a dict with ``baseline_results``, ``evolved_results``,
    ``baseline_metrics``, ``evolved_metrics``, ``comparison``, and ``report``.
    """
    # Run baseline (no genes).
    baseline_results = [run_task(t, genes=None, agent_fn=agent_fn) for t in tasks]
    # Run evolved (with genes).
    evolved_results = [run_task(t, genes=genes, agent_fn=agent_fn) for t in tasks]

    baseline_metrics = compute_metrics(baseline_results)
    evolved_metrics = compute_metrics(evolved_results)
    comparison = compare_metrics(baseline_metrics, evolved_metrics)
    report = format_report(baseline_metrics, evolved_metrics, comparison)

    # Sprint 24.9: statistical thesis verdict (z-test ∧ practical delta ∧ n≥30).
    from evolver.experiment.stats import evaluate_thesis

    thesis = evaluate_thesis(
        int(baseline_metrics.get("successes", 0)),
        int(baseline_metrics.get("total", 0)),
        int(evolved_metrics.get("successes", 0)),
        int(evolved_metrics.get("total", 0)),
    )

    return {
        "baseline_results": baseline_results,
        "evolved_results": evolved_results,
        "baseline_metrics": baseline_metrics,
        "evolved_metrics": evolved_metrics,
        "comparison": comparison,
        "thesis": thesis,
        "report": report,
    }


def run_multi_config(
    tasks: list[dict[str, Any]],
    configs: dict[str, list[dict[str, Any]]],
    *,
    agent_fn: Any | None = None,
) -> dict[str, Any]:
    """Run multiple named configurations and return per-config metrics.

    Parameters:
        tasks: List of task dicts.
        configs: Dict of ``{config_name: gene_list_or_None}``.
            ``None`` means baseline (no genes).
        agent_fn: Agent callable.

    Returns ``{config_name: {results, metrics}}`` for each config.
    """
    results: dict[str, Any] = {}
    for name, gene_set in configs.items():
        task_results = [run_task(t, genes=gene_set, agent_fn=agent_fn) for t in tasks]
        results[name] = {
            "results": task_results,
            "metrics": compute_metrics(task_results),
        }
    return results


__all__ = ["run_comparison", "run_multi_config"]
