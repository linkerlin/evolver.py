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
        help="Path to a file holding the record context (wins over --from-episodes)",
    )
    parser.add_argument(
        "--from-episodes",
        action="store_true",
        help="Build the record context from the episode store with the shared "
        "dispatch renderer (wins over --record-context)",
    )
    parser.add_argument(
        "--episode-id",
        default=None,
        help="Pin one episode by id (implies --from-episodes; overrides --episodes-limit)",
    )
    parser.add_argument(
        "--episodes-limit",
        type=int,
        default=1,
        help="How many latest episodes to render (default: 1, same as dispatch)",
    )
    parser.add_argument(
        "--episode-max-chars",
        type=int,
        default=2000,
        help="Per-episode render budget (default: 2000, same as the renderer)",
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


def build_record_context_from_episodes(
    *,
    limit: int = 1,
    max_chars_per_episode: int = 2000,
    episode_id: str | None = None,
) -> tuple[str, list[str]]:
    """Build the with-records context from the episode store.

    Uses the same renderer the dispatch pipeline uses
    (:func:`evolver.gep.episode_record.render_episode_block`), so "has a
    record" means the same thing in both paths — the bridge that lets a real
    episode feed the ablation without a hand-carried file. Returns
    ``(context, episode_ids)``; an empty store returns ``("", [])`` and the
    caller says so on stderr rather than guessing. A corrupt index raises
    (the store fails loudly by contract); the caller turns that into exit 1.
    """
    from evolver.gep import episode_record

    if episode_id:
        body = episode_record.load_episode(episode_id)
        if body is None:
            return "", []
        return (
            episode_record.render_episode_block(
                body, ep_id=episode_id, max_chars=max_chars_per_episode
            ),
            [episode_id],
        )
    entries = episode_record.list_episodes()
    picked = [e for e in entries if isinstance(e, dict) and e.get("id")][-max(1, limit) :]
    blocks: list[str] = []
    used: list[str] = []
    for entry in picked:
        ep_id = str(entry.get("id") or "")
        body = episode_record.load_episode(ep_id) if ep_id else None
        if body is None:
            continue
        blocks.append(
            episode_record.render_episode_block(body, ep_id=ep_id, max_chars=max_chars_per_episode)
        )
        used.append(ep_id)
    return ("\n\n".join(blocks), used)


def _main_ablation(args: argparse.Namespace, tasks: list[Any]) -> int:
    """Real-LLM ablation: same tasks, with-records vs without-records (§5.9)."""
    from evolver.experiment.ablation_llm import run_llm_ablation
    from evolver.experiment.llm import LLMError
    from evolver.gep.episode_record import EpisodeConflictError

    limit = args.episodes_limit if args.episodes_limit is not None else 1
    per_episode = args.episode_max_chars if args.episode_max_chars is not None else 2000
    if limit < 1:
        print("ablation: --episodes-limit must be >= 1", file=sys.stderr)
        return 2
    if per_episode < 1:
        print("ablation: --episode-max-chars must be >= 1", file=sys.stderr)
        return 2

    # Precedence: file > store > inline. The most explicit source wins, and
    # the winner is recorded in the report — a context with no named source
    # is how a hand-carried file stops being reproducible.
    source = "inline"
    episodes_used: list[str] = []
    if args.record_context_file:
        context = Path(args.record_context_file).read_text(encoding="utf-8")
        source = "file"
        if args.from_episodes or args.episode_id:
            print(
                "ablation: --record-context-file wins over --from-episodes",
                file=sys.stderr,
            )
    elif args.from_episodes or args.episode_id:
        try:
            context, episodes_used = build_record_context_from_episodes(
                limit=limit,
                max_chars_per_episode=per_episode,
                episode_id=args.episode_id,
            )
        except EpisodeConflictError as exc:
            print(f"ablation: episode store unreadable: {exc}", file=sys.stderr)
            return 1
        source = "episode_id" if args.episode_id else "episodes"
        if not episodes_used:
            source = "episodes(empty)"
            print(
                "ablation: --from-episodes found no episodes — with_records runs "
                "empty (expect no_signal)",
                file=sys.stderr,
            )
    else:
        context = args.record_context
        if not context:
            source = "empty"
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
    result["record_context_source"] = source
    result["episodes_used"] = episodes_used
    result["record_context_chars"] = len(context)
    print(
        f"model={result['model_requested']} served={result['server_models']} "
        f"budget={result['budget']}",
        file=sys.stderr,
    )
    print(
        f"context source={source} episodes={episodes_used} chars={len(context)}",
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
