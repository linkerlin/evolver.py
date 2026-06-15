"""Experiment agent runner — execute a single agent on a benchmark task.

Equivalent to ``evolver/src/experiment/agentRunner.js``.

Runs an agent (optionally with evolved genes injected as context) on a
single task and returns the result + usage metrics.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskResult:
    """Result of running a single task."""

    task_id: str
    success: bool
    answer: str = ""
    tokens_used: int = 0
    latency_s: float = 0.0
    gene_ids: list[str] = field(default_factory=list)
    error: str = ""


def run_task(
    task: dict[str, Any],
    *,
    genes: list[dict[str, Any]] | None = None,
    agent_fn: Any | None = None,
) -> TaskResult:
    """Run a single task with optional gene injection.

    Parameters:
        task: Dict with ``id``, ``prompt``, and optional ``expected``.
        genes: Gene dicts to inject as context (None = baseline).
        agent_fn: Callable that takes ``(prompt, context)`` and returns
            ``(answer: str, tokens: int)``. If None, uses a stub.

    Returns a :class:`TaskResult`.
    """
    task_id = task.get("id", "unknown")
    prompt = task.get("prompt", "")

    # Build context from genes.
    context_parts: list[str] = []
    gene_ids: list[str] = []
    if genes:
        for gene in genes:
            gid = gene.get("id", "")
            gene_ids.append(gid)
            summary = gene.get("summary", "")
            strategy = gene.get("strategy", [])
            if summary:
                context_parts.append(f"[Gene {gid}] {summary}")
            for step in strategy[:5]:
                context_parts.append(f"  - {step}")
    context = "\n".join(context_parts)

    # Run the agent.
    start = time.time()
    if agent_fn is not None:
        try:
            answer, tokens = agent_fn(prompt, context)
            latency = time.time() - start
            success = _check_success(task, answer)
            return TaskResult(
                task_id=task_id,
                success=success,
                answer=answer[:2000],
                tokens_used=tokens,
                latency_s=round(latency, 2),
                gene_ids=gene_ids,
            )
        except Exception as exc:
            return TaskResult(
                task_id=task_id,
                success=False,
                error=str(exc),
                latency_s=round(time.time() - start, 2),
                gene_ids=gene_ids,
            )

    # Stub: no agent provided.
    return TaskResult(
        task_id=task_id,
        success=False,
        answer="",
        error="no_agent_fn",
        gene_ids=gene_ids,
    )


def _check_success(task: dict[str, Any], answer: str) -> bool:
    """Check if the answer matches the expected result."""
    expected = task.get("expected")
    if expected is None:
        return bool(answer.strip())
    if isinstance(expected, str):
        return expected.lower().strip() in answer.lower()
    if isinstance(expected, list):
        answer_lower = answer.lower()
        return all(e.lower() in answer_lower for e in expected)
    return bool(answer.strip())


__all__ = ["TaskResult", "run_task"]
