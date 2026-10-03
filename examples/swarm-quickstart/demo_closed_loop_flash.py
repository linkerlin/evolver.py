#!/usr/bin/env python
"""End-to-end closed-loop demo with deepseek-flash as the host executor.

Unlike demo_swarm_loop.py (an MCP surface tour), this script closes the real
loop the charter proposes: tick -> LLM executes -> distill -> host-declared
hypothesis -> solidify -> a REAL episode record -> a REAL ablation that feeds
that episode back through the --from-episodes bridge (with-records vs
without-records, same budget, same tasks).

The ONLY network traffic is DeepSeek. Everything else runs in a disposable
workspace (temp dir): the engine never touches ~/.evomap or this repo.

Model honesty: the model id is pinned to "deepseek-flash" in code (never
inherited from DEEPSEEK_MODEL), and the report cites the server-returned id.
Relay honesty: DeepSeekClient calls api.deepseek.com directly, so relay
coverage for this run is 0% (unmeasured) — printed, not hidden.

Framing honesty: the ablation runs 2 toy tasks (budget=2). Whatever the
verdict, it demonstrates the MECHANISM, not an effect — n=2 proves nothing,
and the script says so. Conclusions stop at process metrics (charter
point-ruling 1: no test-seat reads).

Usage:
    DEEPSEEK_API_KEY=sk-... uv run python \
        examples/swarm-quickstart/demo_closed_loop_flash.py [--keep]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

MODEL_PINNED = "deepseek-flash"
AGENT = "demo-flash-host"

# Synthetic val pack scaffolding, verbatim ids from tests/conftest.py
# SYNTHETIC_VAL_PACK (the hypothesis gate cites train ids, so the pack must
# carry them). Labeled scaffolding: it arms the bar, it is not evidence.
SYNTHETIC_PACK: dict[str, Any] = {
    "pack_version": 1,
    "tasks": [
        {
            "id": "fixture-val-1",
            "split": "val",
            "title": "fixture val task 1",
            "prompt": "Write x to out.txt.",
            "sandbox": {"in.txt": "seed\n"},
            "grader": {"type": "exact", "file": "out.txt", "expected": "x"},
        },
        {
            "id": "fixture-val-2",
            "split": "val",
            "title": "fixture val task 2",
            "prompt": "Write x to out.txt.",
            "sandbox": {"in.txt": "seed\n"},
            "grader": {"type": "exact", "file": "out.txt", "expected": "x"},
        },
        {
            "id": "fixture-train-1",
            "split": "train",
            "title": "fixture train task 1",
            "prompt": "Write x to out.txt.",
            "sandbox": {"in.txt": "seed\n"},
            "grader": {"type": "exact", "file": "out.txt", "expected": "x"},
        },
    ],
}

ABLATION_TASKS: list[dict[str, Any]] = [
    {
        "id": "demo-repair-1",
        "prompt": (
            "Write a Python function `read_value(path)` that opens the file "
            "and returns its stripped text. Reply with ONLY one fenced python "
            "block, nothing else."
        ),
        "expected": "def read_value",
    },
    {
        "id": "demo-neutral-1",
        "prompt": "Reply with ONLY the four letters PONG and nothing else.",
        "expected": "PONG",
    },
]

EXECUTOR_SYSTEM = """You are the executor of the EVOLVER SWARM loop. You receive a
GEP dispatch prompt; this run is sandboxed, so do not attempt file edits.
Reply with (1) a short work summary, then (2) exactly ONE fenced ```json block
with a single valid Gene object using EXACTLY these keys: {"type": "Gene",
"id": "gene_demo_closed_loop", "category": "repair", "summary": "...",
"signals_match": ["ImportError"], "strategy": ["..."], "preconditions": [],
"validation": ["python --version"], "avoid": []}."""


def step(n: int, title: str) -> None:
    print(f"\n[{n}] {title}\n" + "-" * 60)


def show(label: str, value: Any, limit: int = 180) -> None:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(text) > limit:
        text = text[:limit] + " ..."
    print(f"  {label}: {text}")


def abort(reason: str) -> int:
    print(f"\n  !! HONEST ABORT (exit 2): {reason}")
    print("  Nothing was faked to get past this point; fix the cause and re-run.")
    return 2


def isolate(ws: Path) -> None:
    """Point every evolver state dir into the disposable workspace."""
    os.environ["EVOLVER_REPO_ROOT"] = str(ws)
    os.environ["OPENCLAW_WORKSPACE"] = str(ws)
    os.environ["GEP_ASSETS_DIR"] = str(ws / ".evolver" / "gep")
    os.environ["EVOLUTION_DIR"] = str(ws / "memory" / "evolution")
    os.environ["EVOLVER_USER_LOCK"] = str(ws / "user.lock")
    os.environ["EVOLVER_HOME"] = str(ws / ".evomap")
    os.environ["EVOLVER_NO_PARENT_GIT"] = "1"
    os.environ["EVOLVER_HITL_MODE"] = "off"  # explicit: auto-approve with audit
    os.environ["A2A_HUB_URL"] = "http://127.0.0.1:9"  # fast-refused, never real Hub
    os.environ["EVOLVE_LOAD_MAX"] = "999"  # ambient host load must not abort the demo


def git_init(ws: Path) -> None:
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "demo@t"],
        ["git", "config", "user.name", "demo"],
    ):
        subprocess.run(cmd, cwd=ws, check=True, capture_output=True)
    (ws / "README.md").write_text("# closed-loop flash demo workspace\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=ws, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init", "--allow-empty"],
        cwd=ws,
        check=True,
        capture_output=True,
    )


def arm_synthetic_pack() -> None:
    """Mirror tests/conftest.py armed_pack: Parent bar 0.0, candidate slots 1.0."""
    from evolver.bench import frozen_gate

    pack_path = frozen_gate.frozen_pack_path()
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    pack_path.write_text(json.dumps(SYNTHETIC_PACK, indent=2) + "\n", encoding="utf-8")

    def _fill(text: str) -> None:
        for index in (1, 2):
            root = frozen_gate.sandbox_root(pack_path, replicate=index)
            for task in SYNTHETIC_PACK["tasks"]:
                slot = root / str(task["id"])
                slot.mkdir(parents=True, exist_ok=True)
                (slot / "out.txt").write_text(text, encoding="utf-8")

    _fill("wrong")
    parent = frozen_gate.establish_parent_baseline()
    assert parent.get("ok") is True, parent
    _fill("x")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="keep the temp workspace")
    args = parser.parse_args()

    if not (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_APIKEY")):
        print("DEEPSEEK_API_KEY is required (the demo's only network is DeepSeek).")
        return 2

    tmp_ctx = None if args.keep else tempfile.TemporaryDirectory()
    ws = Path(tmp_ctx.name if tmp_ctx else tempfile.mkdtemp(prefix="closed-loop-flash-"))
    ws.mkdir(parents=True, exist_ok=True)
    isolate(ws)
    git_init(ws)
    print(f"workspace: {ws} (disposable; ~/.evomap and this repo untouched)")

    from evolver.experiment.ablation_llm import run_llm_ablation
    from evolver.experiment.cli import build_record_context_from_episodes
    from evolver.experiment.llm import DeepSeekClient, LLMError
    from evolver.gep import episode_record
    from evolver.swarm import (
        swarm_distill,
        swarm_feedback,
        swarm_hook_event,
        swarm_hypothesis,
        swarm_solidify,
        swarm_tick,
    )

    summary: list[tuple[str, str]] = []
    try:
        step(1, "脚手架: 冻结包布防 (Parent bar 0.0, 候选槽 1.0)")
        arm_synthetic_pack()
        show("pack", "synthetic, Parent=0.0, candidate slots=x (strict improvement armed)")
        summary.append(("armed_pack", "Parent 0.0 -> candidate 1.0"))

        step(2, "信号播种 + tick: 产出 GEP 变异提示词 (引擎)")
        hook = swarm_hook_event(
            "signal_detect", {"content": "ImportError: cannot import name read_value"}
        )
        show("hook signals", hook.get("signals"))
        tick = asyncio.run(swarm_tick(agent_name=AGENT))
        prompt = tick.get("dispatch_prompt") or ""
        if not prompt:
            return abort(f"no dispatch prompt ({tick.get('dispatch_reason')})")
        show("run_id", tick.get("run_id"))
        show("dispatch_prompt chars", len(prompt))
        summary.append(("tick", f"run={tick.get('run_id')} chars={len(prompt)}"))

        step(3, "宿主执行: deepseek-flash 跑 dispatch 提示词")
        client = DeepSeekClient(model=MODEL_PINNED, max_tokens=4096)
        try:
            response, usage = client.complete_prompt(prompt, context=EXECUTOR_SYSTEM)
        except LLMError as exc:
            return abort(f"executor call failed: {exc}")
        show("model requested", MODEL_PINNED)
        show("model served", client.last_server_model or "(unrecorded)")
        show("tokens", usage.get("total_tokens"))
        show("response head", response[:220])
        summary.append(
            (
                "execute",
                f"served={client.last_server_model} tokens={usage.get('total_tokens')}",
            )
        )

        step(4, "蒸馏入库 (引擎, 非 dry-run; 一次严格重试)")
        distilled = swarm_distill(response)
        if int(distilled.get("genes") or 0) < 1:
            retry, retry_usage = client.complete_prompt(
                EXECUTOR_SYSTEM + "\n\nYour previous reply had no fenced ```json Gene "
                "block. Reply again with the summary AND exactly one such block.",
                context="",
            )
            show("retry tokens", retry_usage.get("total_tokens"))
            distilled = swarm_distill(retry)
        genes = int(distilled.get("genes") or 0)
        if genes < 1:
            show("distill result", distilled)
            return abort("LLM produced no distillable assets after one strict retry")
        show("genes installed", genes)
        show("clue", distilled.get("clue"))
        summary.append(("distill", f"genes={genes}"))

        step(5, "宿主声明假说 (引擎永不代笔, §5.3)")
        hyp = swarm_hypothesis(
            {
                "hypothesis": "repairing the missing import resolves the ImportError",
                "dimension": "content",
                "mechanism_family": "test-fixture",
                "target_hook": "tests/",
                "mechanism_check": [
                    {
                        "id": "fixture-train-1",
                        "before": "fixture train task graded 0 in its sandbox",
                        "after": "replayed after the change",
                    }
                ],
            },
            agent_name=AGENT,
        )
        if not hyp.get("ok"):
            show("hypothesis result", hyp)
            return abort(f"hypothesis rejected: {hyp.get('message')}")
        show("hypothesis", hyp.get("hypothesis_path"))
        summary.append(("hypothesis", "declared by host"))

        step(6, "固化结算 (引擎; skip_validation 只跳命令级联, 门照跑)")
        print("  note: skip_validation=True skips shell validation commands only;")
        print("  note: hypothesis/bench/acceptance gates still run. HITL=off audit.")
        solidified = swarm_solidify(skip_validation=True)
        if not solidified.get("ok"):
            show("solidify result", solidified)
            return abort(f"round settled as Reject: {solidified.get('error')}")
        episode = solidified.get("episode") or {}
        if not episode.get("ok"):
            show("episode", episode)
            return abort("settled round left no episode record")
        show("event_id", solidified.get("event_id"))
        show("episode id", episode.get("id"))
        summary.append(("solidify", f"Accept event={solidified.get('event_id')}"))

        step(7, "评估信号 E (宿主上报本轮结果)")
        feedback = swarm_feedback(
            primary_score=1.0,
            textual_gradient="flash executor: Accept round, episode recorded",
            agent_name=AGENT,
        )
        show("degraded", feedback.get("degraded"))
        summary.append(("feedback", f"degraded={feedback.get('degraded')}"))

        step(8, "真实消融: 刚产出的 episode 经取材桥喂回对照 (引擎+宿主)")
        context, used = build_record_context_from_episodes(limit=1)
        show("record_context_source", "episodes" if used else "episodes(empty)")
        show("episodes_used", used)
        if not used:
            return abort("episode store empty after an Accepted round (bug)")
        try:
            report = run_llm_ablation(
                ABLATION_TASKS,
                context,
                model=MODEL_PINNED,
                max_tokens=2048,
                budget=2,
                success_mode="contains",
            )
        except LLMError as exc:
            return abort(f"ablation call failed: {exc}")
        for arm in ("with_records", "without_records"):
            metrics = report[arm]
            show(arm, f"{metrics['successes']}/{metrics['total']} tokens={metrics['total_tokens']}")
        show("delta", report["comparison"].get("success_rate_pct"))
        show("token delta", report["comparison"].get("token_delta_pct"))
        show("verdict", report["verdict"]["verdict"])
        show("served", report["server_models"])
        show("errors", report["errors"])
        show("relay coverage", "0% (unmeasured, direct api.deepseek.com)")
        summary.append(("ablation", f"verdict={report['verdict']['verdict']}"))

        step(9, "证据盘点 (引擎侧一等对象)")
        index = episode_record.list_episodes()
        show("episodes in store", len(index))
        show("fresh episode", used[0] if used else "(none)")
        summary.append(("episodes", f"store={len(index)}"))
    finally:
        if tmp_ctx:
            time.sleep(0.2)
            tmp_ctx.cleanup()

    print("\n" + "=" * 60)
    print("CLOSED-LOOP SUMMARY (deepseek-flash)")
    print("=" * 60)
    for name, result in summary:
        print(f"  {name:<12} {result}")
    print("\n诚实边界: 消融 n=2 玩具题, 只演示机制能跑通, 不支撑任何结论;")
    print("结论止于过程指标, 不外推下游能力 (点名裁决 1).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
