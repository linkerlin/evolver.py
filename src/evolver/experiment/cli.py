"""Experiment CLI — run controlled experiments from the command line.

Equivalent to ``evolver/src/experiment/cli.js``.

Usage::

    evolver experiment --tasks tasks.json --genes genes.json
    python -m evolver.experiment.cli --tasks tasks.json  # baseline only
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a controlled evolution experiment")
    parser.add_argument(
        "--tasks", required=True, help="Path to tasks JSON file (list of task dicts)"
    )
    parser.add_argument(
        "--genes", default=None, help="Path to genes JSON file (list of gene dicts)"
    )
    parser.add_argument(
        "--output", default=None, help="Path to write results JSON (default: stdout)"
    )
    parser.add_argument(
        "--ablation",
        action="store_true",
        help="Run the real-LLM with/without-records ablation (§5.9) instead of baseline-vs-evolved",
    )
    parser.add_argument(
        "--record-context", default="", help="Record context text for the with-records arm"
    )
    parser.add_argument(
        "--record-context-file",
        default=None,
        help="Path to a file holding the record context (wins over --record-context)",
    )
    parser.add_argument(
        "--model",
        default="deepseek-flash",
        help="LLM model id, pinned explicitly (default: deepseek-flash)",
    )
    parser.add_argument(
        "--success-mode",
        default="contains",
        choices=["exact", "contains"],
        help="How a task's expected text is checked (default: contains)",
    )
    parser.add_argument("--budget", type=int, default=None, help="Max tasks per arm (default: all)")
    parser.add_argument(
        "--max-tokens", type=int, default=16384, help="Per-call token budget (default: 16384)"
    )
    args = parser.parse_args(argv)

    tasks = _load_json(args.tasks)
    if not isinstance(tasks, list):
        print("Tasks file must be a JSON list", file=sys.stderr)
        return 1

    if args.ablation:
        return _main_ablation(args, tasks)

    genes = None
    if args.genes:
        genes = _load_json(args.genes)
        if not isinstance(genes, list):
            print("Genes file must be a JSON list", file=sys.stderr)
            return 1

    from evolver.experiment.comparison import run_comparison

    result = run_comparison(tasks, genes=genes)

    # Print the report to stderr (human-readable), write metrics to stdout/output.
    print(result["report"], file=sys.stderr)

    output_data = {
        "baseline_metrics": result["baseline_metrics"],
        "evolved_metrics": result["evolved_metrics"],
        "comparison": result["comparison"],
    }
    output_json = json.dumps(output_data, indent=2, default=str)

    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(output_json)
    return 0


def _main_ablation(args: argparse.Namespace, tasks: list[Any]) -> int:
    """Real-LLM ablation: same tasks, with-records vs without-records (§5.9)."""
    from evolver.experiment.ablation_llm import run_llm_ablation
    from evolver.experiment.llm import LLMError

    context = args.record_context
    if args.record_context_file:
        context = Path(args.record_context_file).read_text(encoding="utf-8")
    try:
        result = run_llm_ablation(
            tasks,
            context,
            model=args.model,
            max_tokens=args.max_tokens,
            budget=args.budget,
            success_mode=args.success_mode,
        )
    except LLMError as exc:
        print(f"ablation: {exc}", file=sys.stderr)
        return 2

    verdict = result["verdict"]
    print(
        f"model={result['model_requested']} served={result['server_models']} "
        f"budget={result['budget']}",
        file=sys.stderr,
    )
    for arm in ("with_records", "without_records"):
        metrics = result[arm]
        print(
            f"{arm}: {metrics['successes']}/{metrics['total']} "
            f"tokens={metrics['total_tokens']} errors="
            f"{sum(1 for e in result['errors'] if e['arm'] == arm)}",
            file=sys.stderr,
        )
    print(
        f"delta={result['comparison']['success_rate_pct']} "
        f"tokens={result['comparison']['token_delta_pct']} "
        f"verdict={verdict['verdict']} ({verdict['conclusion']})",
        file=sys.stderr,
    )

    output_json = json.dumps(result, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
