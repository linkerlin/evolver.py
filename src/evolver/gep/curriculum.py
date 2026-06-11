"""Curriculum manager — progressive task sequencing for GEP.

Equivalent to Node's ``evolver/src/gep/curriculum.js``.

Manages a curriculum of learning tasks with increasing difficulty.
Tasks are drawn from:
1. Exploration results (:mod:`explore`).
2. Past failures (:mod:`memory_graph`).
3. User-defined milestones.

Each task has a difficulty level (1-5). The curriculum advances
when the agent demonstrates mastery (success rate > threshold).

Design notes
------------
* Curriculum state is persisted to ``evolver/.config/curriculum.json``.
* Uses atomic writes (tmp + replace).
* Deterministic ordering — tasks are sorted by difficulty then priority.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evolver.gep.feature_flags import is_enabled
from evolver.gep.paths import get_workspace_root

logger = logging.getLogger(__name__)

CURRICULUM_PATH = Path("evolver") / ".config" / "curriculum.json"

# Mastery threshold: success rate must exceed this to advance
MASTERY_THRESHOLD = 0.75

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CurriculumTask:
    task_id: str
    description: str
    difficulty: int = 3  # 1-5
    priority: float = 0.5  # 0-1
    attempts: int = 0
    successes: int = 0
    completed: bool = False
    created_at: float = field(default_factory=time.time)
    source: str = ""  # e.g. "explore", "memory", "user"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "difficulty": self.difficulty,
            "priority": self.priority,
            "attempts": self.attempts,
            "successes": self.successes,
            "completed": self.completed,
            "created_at": self.created_at,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CurriculumTask":
        return cls(
            task_id=d["task_id"],
            description=d.get("description", ""),
            difficulty=d.get("difficulty", 3),
            priority=d.get("priority", 0.5),
            attempts=d.get("attempts", 0),
            successes=d.get("successes", 0),
            completed=d.get("completed", False),
            created_at=d.get("created_at", time.time()),
            source=d.get("source", ""),
        )

    @property
    def success_rate(self) -> float:
        if self.attempts == 0:
            return 0.0
        return self.successes / self.attempts


@dataclass
class CurriculumState:
    current_level: int = 1
    tasks: list[CurriculumTask] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_level": self.current_level,
            "tasks": [t.to_dict() for t in self.tasks],
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CurriculumState":
        return cls(
            current_level=d.get("current_level", 1),
            tasks=[CurriculumTask.from_dict(t) for t in d.get("tasks", [])],
            last_updated=d.get("last_updated", time.time()),
        )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _curriculum_path() -> Path:
    return get_workspace_root() / CURRICULUM_PATH


def load_state() -> CurriculumState:
    """Load curriculum state from disk, or return a fresh state."""
    path = _curriculum_path()
    if not path.exists():
        return CurriculumState()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return CurriculumState.from_dict(raw)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[Curriculum] Failed to load state: %s", exc)
        return CurriculumState()


def save_state(state: CurriculumState) -> None:
    """Persist *state* to disk."""
    path = _curriculum_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Task management
# ---------------------------------------------------------------------------


def add_task(
    task_id: str,
    description: str,
    difficulty: int = 3,
    priority: float = 0.5,
    source: str = "",
) -> CurriculumTask:
    """Add a new task to the curriculum."""
    state = load_state()
    task = CurriculumTask(
        task_id=task_id,
        description=description,
        difficulty=max(1, min(5, difficulty)),
        priority=priority,
        source=source,
    )
    # Replace if same task_id exists
    state.tasks = [t for t in state.tasks if t.task_id != task_id]
    state.tasks.append(task)
    state.last_updated = time.time()
    save_state(state)
    return task


def record_attempt(task_id: str, success: bool) -> CurriculumTask | None:
    """Record an attempt result for *task_id*."""
    state = load_state()
    for t in state.tasks:
        if t.task_id == task_id:
            t.attempts += 1
            if success:
                t.successes += 1
            # Auto-complete if mastery reached
            if t.success_rate >= MASTERY_THRESHOLD and t.attempts >= 3:
                t.completed = True
            state.last_updated = time.time()
            save_state(state)
            return t
    return None


def advance_level() -> int:
    """Advance the curriculum level if mastery is demonstrated.

    Returns the new level.
    """
    state = load_state()
    current_tasks = [t for t in state.tasks if t.difficulty == state.current_level and not t.completed]
    if not current_tasks:
        # All tasks at current level completed — advance
        state.current_level = min(5, state.current_level + 1)
        state.last_updated = time.time()
        save_state(state)
        logger.info("[Curriculum] Advanced to level %d", state.current_level)
    return state.current_level


# ---------------------------------------------------------------------------
# Sequencing
# ---------------------------------------------------------------------------


def next_tasks(
    *,
    count: int = 3,
    level: int | None = None,
) -> list[CurriculumTask]:
    """Return the next *count* tasks at the given level (or current level).

    Tasks are sorted by: completed first, then priority desc, then created_at asc.
    """
    if not is_enabled("enable_curriculum"):
        return []
    state = load_state()
    target = level if level is not None else state.current_level
    candidates = [t for t in state.tasks if t.difficulty == target and not t.completed]
    # Sort: higher priority first, older first
    candidates.sort(key=lambda t: (-t.priority, t.created_at))
    return candidates[:count]


def ingest_exploration_tasks(exploration_signals: list[dict[str, Any]]) -> int:
    """Convert exploration signals into curriculum tasks.

    Returns the number of new tasks added.
    """
    state = load_state()
    added = 0
    for sig in exploration_signals:
        task_id = f"explore:{sig.get('file_path','')}:{sig.get('line',0)}:{sig.get('task_type','')}"
        if not any(t.task_id == task_id for t in state.tasks):
            task = CurriculumTask(
                task_id=task_id,
                description=sig.get("description", ""),
                difficulty=min(5, max(1, int(sig.get("priority", 0.5) * 5))),
                priority=sig.get("priority", 0.5),
                source="explore",
            )
            state.tasks.append(task)
            added += 1
    if added:
        state.last_updated = time.time()
        save_state(state)
        logger.info("[Curriculum] Ingested %d exploration tasks", added)
    return added
