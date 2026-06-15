"""Experiment CLI — run controlled experiments from the command line.

Equivalent to ``evolver/src/experiment/cli.js``.

Usage::

    python -m evolver.experiment.cli --tasks tasks.json --genes genes.json
    python -m evolver.experiment.cli --tasks tasks.json  # baseline only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a controlled evolution experiment"
    )
    parser.add_argument(
        "--tasks", required=True, help="Path to tasks JSON file (list of task dicts)"
    )
    parser.add_argument(
        "--genes", default=None, help="Path to genes JSON file (list of gene dicts)"
    )
    parser.add_argument(
        "--output", default=None, help="Path to write results JSON (default: stdout)"
    )
    args = parser.parse_args()

    tasks = _load_json(args.tasks)
    if not isinstance(tasks, list):
        print("Tasks file must be a JSON list", file=sys.stderr)
        raise SystemExit(1)

    genes = None
    if args.genes:
        genes = _load_json(args.genes)
        if not isinstance(genes, list):
            print("Genes file must be a JSON list", file=sys.stderr)
            raise SystemExit(1)

    from evolver.experiment.comparison import run_comparison  # noqa: PLC0415

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


if __name__ == "__main__":
    main()
