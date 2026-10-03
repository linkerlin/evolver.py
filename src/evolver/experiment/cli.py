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
        "--placebo",
        action="store_true",
        help="Give the without-records arm a neutral same-length system block instead of "
        "none, so the arms differ by record content only (not by system-role presence)",
    )
    parser.add_argument(
        "--stage-exit",
        action="store_true",
        help="Stage-exit contract (§5.8/§5.9): only real --from-episodes with "
        "--placebo, unique tasks, seeded AB/BA interleaving, per-call records, "
        "and a paired verdict. Ineligible setups exit 2 instead of reporting.",
    )
    parser.add_argument(
        "--order-seed",
        type=int,
        default=0,
        help="Seed for the AB/BA interleave order (default: 0; recorded in the report)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Freeze the LLM sampling temperature (default: unset — provider default, "
        "recorded as such)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Freeze the LLM sampling seed, when the provider honors one "
        "(default: unset — recorded as such)",
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


def _detect_commit() -> str:
    """The code commit the run binds to ("" when not in a git repo).

    A module-level seam so tests can pin it; the stage-exit contract refuses
    an unknown commit rather than letting a report float free of the code.
    """
    from evolver.gep.git_ops import try_run_cmd

    return try_run_cmd(["rev-parse", "HEAD"]).strip()


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
    if args.stage_exit:
        if not (args.from_episodes or args.episode_id):
            print(
                "stage-exit: requires --from-episodes or --episode-id "
                "(real episodes only — inline/file context cannot exit the stage)",
                file=sys.stderr,
            )
            return 2
        if not args.placebo:
            print(
                "stage-exit: requires --placebo (the control arm must differ "
                "by record content only)",
                file=sys.stderr,
            )
            return 2
        if not args.output:
            print(
                "stage-exit: requires --output (the report must land on disk to be replayable)",
                file=sys.stderr,
            )
            return 2
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
    if args.stage_exit:
        # A file pinned next to --from-episodes would still win the precedence
        # above — and smuggle a hand-carried context into a stage exit. Only
        # the episode store may feed this mode.
        if source not in ("episodes", "episode_id"):
            print(
                f"stage-exit: record context must come from the episode store "
                f"(got source={source})",
                file=sys.stderr,
            )
            return 2
        if not episodes_used:
            print(
                "stage-exit: --from-episodes found no episodes — an exit with "
                "an empty with_records arm proves nothing",
                file=sys.stderr,
            )
            return 2
        return _main_stage_exit(args, tasks, context, episodes_used)
    from evolver.experiment.ablation import make_placebo_context

    control = make_placebo_context(context) if args.placebo else ""
    try:
        result = run_llm_ablation(
            tasks,
            context,
            model=args.model,
            max_tokens=args.max_tokens,
            budget=args.budget,
            success_mode=args.success_mode,
            control_context=control,
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
    print(
        f"control={verdict.get('control', 'empty')} "
        f"n_per_arm={verdict.get('n_per_arm', 'n/a')} "
        f"sample_adequate={verdict.get('sample_adequate', 'n/a')} "
        f"basis={verdict.get('signal_basis', 'n/a')}",
        file=sys.stderr,
    )

    output_json = json.dumps(result, indent=2, default=str)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(output_json)
    return 0


def _main_stage_exit(
    args: argparse.Namespace,
    tasks: list[Any],
    context: str,
    episodes_used: list[str],
) -> int:
    """Stage-exit ablation: the machine-checkable form of ``_main_ablation``.

    Preconditions (exit 2): real episodes, placebo control, ``--output``.
    Postconditions (in the report, never guessed): task-set integrity and
    digest, code commit, sampling params, order seed, per-call records, the
    paired verdict, and the eligibility verdict. The process exit stays 0
    once the run completes — the verdict carries the weight, not the code.
    """
    from evolver.experiment import ablation_llm
    from evolver.experiment.ablation import (
        check_stage_eligibility,
        check_task_set,
        make_placebo_context,
        stage_exit_verdict,
    )
    from evolver.experiment.llm import LLMError

    try:
        check_task_set(tasks)
    except ValueError as exc:
        print(f"stage-exit: {exc}", file=sys.stderr)
        return 2
    try:
        result = ablation_llm.run_llm_stage_exit(
            tasks,
            context,
            model=args.model,
            max_tokens=args.max_tokens,
            budget=args.budget,
            success_mode=args.success_mode,
            control_context=make_placebo_context(context),
            order_seed=args.order_seed,
            temperature=args.temperature,
            seed=args.seed,
        )
    except LLMError as exc:
        print(f"stage-exit: {exc}", file=sys.stderr)
        return 2

    evidence: dict[str, Any] = {
        "episodes_used": episodes_used,
        "control": result["control"],
        "tasks_unique": True,
        "task_digest": result["task_digest"],
        "commit": _detect_commit(),
        "order_seed": result["order_seed"],
        "sampling": result["sampling"],
        "report_path": args.output,
    }
    eligible, reasons = check_stage_eligibility(evidence)
    result["record_context_source"] = "episodes"
    result["episodes_used"] = episodes_used
    result["record_context_chars"] = len(context)
    result["stage_exit_evidence"] = evidence
    verdict = stage_exit_verdict(result)
    result["stage_exit"] = verdict
    paired = verdict["paired"]
    print(
        f"model={result['model_requested']} served={result['server_models']} "
        f"budget={result['budget']} seed={result['order_seed']}",
        file=sys.stderr,
    )
    print(
        f"episodes={episodes_used} digest={result['task_digest'][:19]}... "
        f"commit={evidence['commit'][:12] or 'unknown'}",
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
        f"paired={paired.get('verdict')} p={paired.get('p')} "
        f"discordant={paired.get('discordant')} "
        f"prompt_balance={result['prompt_token_balance'].get('status')}",
        file=sys.stderr,
    )
    print(
        f"eligible={eligible} stage={verdict['stage']} basis={verdict.get('signal_basis', 'n/a')}",
        file=sys.stderr,
    )
    if not eligible:
        print(f"ineligible: {'; '.join(reasons)}", file=sys.stderr)
    output_json = json.dumps(result, indent=2, default=str)
    Path(str(args.output)).write_text(output_json, encoding="utf-8")
    print(f"Results written to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
