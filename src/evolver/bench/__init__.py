"""Benchmark subsystem (S26.1): measurable task surface + health scoring.

演进方案_wikiskill对照版.md §S26.1 — the measurement half of the fitness
revolution. Health tasks grade the workspace itself; task packs (wikiskill
format) bring graded external tasks once an agent executor is wired.
"""

from __future__ import annotations

from evolver.bench.runner import (
    HEALTH_TASKS,
    grade_pack_task,
    load_pack,
    pack_prompt,
    run_health,
    run_pack,
)
from evolver.bench.scoring import grade
from evolver.bench.tasks import materialize, validate_tasks

__all__ = [
    "HEALTH_TASKS",
    "grade",
    "grade_pack_task",
    "load_pack",
    "materialize",
    "pack_prompt",
    "run_health",
    "run_pack",
    "validate_tasks",
]
