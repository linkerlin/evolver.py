"""Task receiver — pull external tasks from Hub and inject as local signals.

Equivalent to Node's ``evolver/src/gep/taskReceiver.js``.

Polls the Hub ``/a2a/task/open`` endpoint, scores tasks by ROI
(bounty / estimated effort) and capability match (task signals vs
local gene pool), and auto-claims high-value tasks.

Claimed tasks are injected as ``external_task`` signals into the
normal GEP pipeline.

Safety limits
-------------
* Max 3 concurrent external tasks.
* 1h warning before deadline.
* Cool-down: same task type 24h.

Design notes
------------
* Uses :mod:`atp.hub_client` for Hub communication.
* Persists claimed tasks to ``memory/external-tasks.jsonl``.
* Respects ``enable_task_receiver`` feature flag.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evolver.gep.feature_flags import is_enabled
from evolver.gep.memory_graph import try_read_memory_graph_events
from evolver.gep.paths import get_workspace_root
from evolver.gep.skill2gep import skill_genes_to_selector_pool, scan_skills

logger = logging.getLogger(__name__)

# Limits
MAX_CONCURRENT_EXTERNAL = 3
ROI_THRESHOLD = 1.5
MATCH_THRESHOLD = 0.6
COOLDOWN_SECONDS = 86400  # 24 h
WARNING_BEFORE_DEADLINE = 3600  # 1 h

TASK_LOG_PATH = Path("memory") / "external-tasks.jsonl"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ExternalTask:
    task_id: str
    task_type: str
    bounty: float
    deadline: float
    signals: list[str]
    estimated_hours: float = 1.0
    claimed_at: float = field(default_factory=time.time)
    status: str = "claimed"  # claimed|in_progress|completed|abandoned

    def roi(self) -> float:
        if self.estimated_hours <= 0:
            return float("inf")
        return self.bounty / self.estimated_hours

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "bounty": self.bounty,
            "deadline": self.deadline,
            "signals": self.signals,
            "estimated_hours": self.estimated_hours,
            "claimed_at": self.claimed_at,
            "status": self.status,
        }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _capability_match(task_signals: list[str], local_genes: list[dict[str, Any]]) -> float:
    """Return match score (0-1) between *task_signals* and *local_genes*."""
    if not task_signals or not local_genes:
        return 0.0
    task_keywords: set[str] = set()
    for s in task_signals:
        task_keywords.update(s.lower().split())

    max_score = 0.0
    for gene in local_genes:
        gene_keywords: set[str] = set()
        for attr in ("signal_keywords", "intent", "name"):
            val = gene.get(attr, "")
            if isinstance(val, str):
                gene_keywords.update(val.lower().split())
            elif isinstance(val, list):
                for v in val:
                    if isinstance(v, str):
                        gene_keywords.update(v.lower().split())
        if not gene_keywords:
            continue
        intersection = task_keywords & gene_keywords
        union = task_keywords | gene_keywords
        score = len(intersection) / len(union) if union else 0.0
        max_score = max(max_score, score)

    return max_score


# ---------------------------------------------------------------------------
# Task log
# ---------------------------------------------------------------------------


def _load_claimed_tasks(path: Path | None = None) -> list[ExternalTask]:
    p = path or (get_workspace_root() / TASK_LOG_PATH)
    if not p.exists():
        return []
    tasks: list[ExternalTask] = []
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    tasks.append(ExternalTask(**obj))
                except (json.JSONDecodeError, TypeError):
                    continue
    except OSError:
        pass
    return tasks


def _save_task(task: ExternalTask, path: Path | None = None) -> None:
    p = path or (get_workspace_root() / TASK_LOG_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(task.to_dict(), ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Hub polling
# ---------------------------------------------------------------------------


def _poll_open_tasks() -> list[dict[str, Any]]:
    """Poll Hub for open tasks. Returns a list of task dicts."""
    if not is_enabled("enable_task_receiver"):
        return []
    try:
        from evolver.atp.hub_client import list_open_tasks
        # list_open_tasks may be async; wrap if needed
        import asyncio
        try:
            return asyncio.run(list_open_tasks())
        except RuntimeError:
            # Already in event loop
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(list_open_tasks())
    except Exception as exc:
        logger.debug("[TaskReceiver] Failed to poll tasks: %s", exc)
        return []


def _claim_task(task_id: str) -> bool:
    """Claim a task on the Hub."""
    try:
        from evolver.atp.hub_client import claim_task
        import asyncio
        try:
            result = asyncio.run(claim_task(task_id))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(claim_task(task_id))
        return bool(result)
    except Exception as exc:
        logger.debug("[TaskReceiver] Failed to claim task %s: %s", task_id, exc)
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def receive_tasks(
    *,
    local_genes: list[dict[str, Any]] | None = None,
    max_concurrent: int = MAX_CONCURRENT_EXTERNAL,
    path: Path | None = None,
) -> list[ExternalTask]:
    """Poll, score, and claim external tasks.

    Returns the list of newly claimed tasks.
    """
    if not is_enabled("enable_task_receiver"):
        return []

    if local_genes is None:
        local_genes = skill_genes_to_selector_pool(scan_skills())

    claimed = _load_claimed_tasks(path)
    now = time.time()

    # Prune completed/abandoned old tasks
    active = [t for t in claimed if t.status in ("claimed", "in_progress")]

    # Check concurrent limit
    if len(active) >= max_concurrent:
        logger.info("[TaskReceiver] At concurrent limit (%d)", max_concurrent)
        return []

    # Cool-down filter
    recent_types = {t.task_type for t in claimed if (now - t.claimed_at) < COOLDOWN_SECONDS}

    open_tasks = _poll_open_tasks()
    new_claims: list[ExternalTask] = []

    for task in open_tasks:
        task_id = task.get("task_id", "")
        task_type = task.get("task_type", "")
        bounty = float(task.get("bounty", 0.0))
        deadline = float(task.get("deadline", now + 86400))
        signals = task.get("signals", [])
        estimated = float(task.get("estimated_hours", 1.0))

        # Skip if already claimed
        if any(t.task_id == task_id for t in claimed):
            continue

        # Skip if in cool-down
        if task_type in recent_types:
            continue

        # Skip if deadline too close
        if deadline - now < WARNING_BEFORE_DEADLINE:
            continue

        # Score
        match_score = _capability_match(signals, local_genes)
        roi = bounty / estimated if estimated > 0 else 0.0

        if match_score < MATCH_THRESHOLD or roi < ROI_THRESHOLD:
            continue

        # Claim
        if _claim_task(task_id):
            ext = ExternalTask(
                task_id=task_id,
                task_type=task_type,
                bounty=bounty,
                deadline=deadline,
                signals=signals,
                estimated_hours=estimated,
            )
            _save_task(ext, path)
            new_claims.append(ext)
            logger.info(
                "[TaskReceiver] Claimed task %s (roi=%.2f, match=%.2f)",
                task_id,
                roi,
                match_score,
            )

        if len(active) + len(new_claims) >= max_concurrent:
            break

    return new_claims


def get_active_tasks(path: Path | None = None) -> list[ExternalTask]:
    """Return all active (claimed/in_progress) external tasks."""
    return [t for t in _load_claimed_tasks(path) if t.status in ("claimed", "in_progress")]


def warn_upcoming_deadlines(
    *,
    warning_seconds: float = WARNING_BEFORE_DEADLINE,
    path: Path | None = None,
) -> list[ExternalTask]:
    """Return tasks whose deadline is within *warning_seconds*."""
    now = time.time()
    urgent: list[ExternalTask] = []
    for t in _load_claimed_tasks(path):
        if t.status not in ("claimed", "in_progress"):
            continue
        remaining = t.deadline - now
        if 0 < remaining < warning_seconds:
            urgent.append(t)
            logger.warning(
                "[TaskReceiver] Task %s deadline in %.0f minutes",
                t.task_id,
                remaining / 60,
            )
    return urgent
