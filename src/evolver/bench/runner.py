"""Bench runner (S26.1): built-in health tasks + score → fitness ledger.

No Node.js equivalent; evolver.py addition.

The health set is the workspace's own "does the repo still work" surface —
the same tooling as the solidify fitness cascade, but standalone, weighted,
and fed into the r_best ledger so ``evolver bench run`` alone advances the
strict-improvement gate. Task-pack support (agent-graded sandboxes) rides on
:mod:`evolver.bench.tasks` / :mod:`evolver.bench.scoring` and gains a runner
when an agent executor is wired (bridge mode).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from evolver.bench.prompts import inference_prompt
from evolver.bench.scoring import grade
from evolver.bench.tasks import materialize, validate_tasks
from evolver.gep.fitness_state import record_measurement
from evolver.gep.paths import get_workspace_root

HEALTH_TASK_TIMEOUT_S = 300.0

HEALTH_TASKS: list[dict[str, Any]] = [
    {"id": "health-ruff", "command": ["ruff", "check", "src", "tests"], "weight": 1.0},
    {"id": "health-mypy", "command": ["mypy", "src"], "weight": 1.0},
    {
        "id": "health-pytest-fast",
        "command": ["pytest", "-x", "-q", "-m", "not slow"],
        "weight": 2.0,
        "timeout_s": HEALTH_TASK_TIMEOUT_S,
    },
]


def run_health(*, record: bool = True, source: str = "bench") -> dict[str, Any]:
    """Run the health set, print per-task verdicts, return the weighted score.

    Tasks whose executable is missing from PATH are skipped (same degradation
    rule as the solidify cascade). Returns ``{"score", "per_task", "verdict"}``.
    """
    cwd = get_workspace_root()
    per_task: list[dict[str, Any]] = []
    total_weight = 0.0
    earned = 0.0
    for spec in HEALTH_TASKS:
        argv = list(spec["command"])
        if shutil.which(argv[0]) is None:
            per_task.append({"id": spec["id"], "status": "skipped", "score": None})
            continue
        started = time.time()
        try:
            proc = subprocess.run(
                argv,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=float(spec.get("timeout_s", HEALTH_TASK_TIMEOUT_S)),
                check=False,
                shell=False,
            )
            ok = proc.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            ok = False
        weight = float(spec.get("weight", 1.0))
        total_weight += weight
        earned += weight if ok else 0.0
        per_task.append(
            {
                "id": spec["id"],
                "status": "pass" if ok else "fail",
                "score": 1.0 if ok else 0.0,
                "seconds": round(time.time() - started, 1),
            }
        )
    score: float | None = round(earned / total_weight, 4) if total_weight else None
    verdict = record_measurement(score, source=f"{source}:health") if record else None
    for row in per_task:
        print(
            f"  {row['id']}: {row['status']}"
            + (f" ({row['score']})" if row["score"] is not None else "")
        )
    if score is None:
        print("bench: no health task runnable (nothing scored)")
    else:
        print(f"bench health R={score}")
        if verdict is not None:
            print(f"fitness gate: {verdict['verdict']} (r_best={verdict['r_best']})")
    return {"score": score, "per_task": per_task, "verdict": verdict}


__all__ = [
    "HEALTH_TASKS",
    "grade_pack_task",
    "load_pack",
    "pack_prompt",
    "run_health",
    "run_pack",
]


# ---------------------------------------------------------------------------
# Task packs (S26.1c): semi-automatic agent executor — print prompt, grade later
# ---------------------------------------------------------------------------


def load_pack(path: Path) -> list[dict[str, Any]]:
    """Load + validate a task pack; raises ValueError on bad input. Accepts
    both the wrapped ``{"pack_version", "tasks"}`` file and a bare list."""
    from evolver.bench.builtin_pack import load_builtin_tasks

    tasks = load_builtin_tasks(json.loads(path.read_text(encoding="utf-8")))
    errors = validate_tasks(tasks)
    if errors:
        raise ValueError("invalid task pack:\n" + "\n".join(f"  - {e}" for e in errors))
    return tasks


def _pack_sandbox_root(pack_path: Path) -> Path:
    """Sandboxes live next to the pack: <pack-dir>/sandboxes/<task-id>/."""
    return pack_path.resolve().parent / "sandboxes"


def pack_prompt(pack_path: Path, task_id: str) -> str:
    """Materialize the task sandbox (force — stale artifacts deleted) and
    return the inference prompt for an external agent. The engine never runs
    an agent; the prompt is the interface (bridge-mode contract)."""
    tasks = {str(t["id"]): t for t in load_pack(pack_path)}
    if task_id not in tasks:
        raise ValueError(f"task {task_id!r} not in pack")
    sandbox = materialize(tasks[task_id], _pack_sandbox_root(pack_path), force=True)
    return inference_prompt(tasks[task_id], sandbox)


def grade_pack_task(pack_path: Path, task_id: str) -> float:
    """Grade one pack task's deliverable (no ledger write — single 0/1 scores
    never move r_best; use run_pack for the aggregated measurement)."""
    tasks = {str(t["id"]): t for t in load_pack(pack_path)}
    if task_id not in tasks:
        raise ValueError(f"task {task_id!r} not in pack")
    sandbox = _pack_sandbox_root(pack_path) / task_id
    if not sandbox.exists():
        raise ValueError(f"sandbox missing: {sandbox} (run 'bench prompt' first)")
    return grade(tasks[task_id], sandbox)


def run_pack(
    pack_path: Path,
    *,
    split: str = "val",
    record: bool = True,
    source: str = "bench",
    output: Path | None = None,
) -> dict[str, Any]:
    """Grade every task in the pack for *split* (S26.4: gate ONLY on val) and
    feed the aggregated R into the fitness ledger.

    Tasks whose sandbox does not exist yet are reported as ``pending`` (their
    prompt has not been run by an agent) and excluded from the score.
    ``output`` persists the per-task results for ``bench compare``.
    """
    tasks = [t for t in load_pack(pack_path) if t["split"] == split]
    root = _pack_sandbox_root(pack_path)
    per_task: list[dict[str, Any]] = []
    earned = 0.0
    counted = 0
    for t in tasks:
        tid = str(t["id"])
        sandbox = root / tid
        if not sandbox.exists():
            per_task.append({"id": tid, "status": "pending"})
            continue
        task_score = grade(t, sandbox)
        earned += task_score
        counted += 1
        per_task.append({"id": tid, "status": "graded", "score": task_score})
    score: float | None = round(earned / counted, 4) if counted else None
    verdict = record_measurement(score, source=f"{source}:pack:{split}") if record else None
    for row in per_task:
        extra = f" ({row['score']})" if row.get("score") is not None else ""
        print(f"  {row['id']}: {row['status']}{extra}")
    if score is None:
        print(f"bench pack: no graded tasks in split={split!r}")
    else:
        print(f"bench pack R[{split}]={score} ({counted}/{len(tasks)} graded)")
        if verdict is not None:
            print(f"fitness gate: {verdict['verdict']} (r_best={verdict['r_best']})")
    result = {
        "pack": str(pack_path),
        "split": split,
        "score": score,
        "per_task": per_task,
        "verdict": verdict,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"results written: {output}")
    return result
