"""Ablation adjudication (经验即证据 §5.8) — the stage exit.

SelfSearch's ablation: does giving the improver access to previous episode
records improve outcomes? This module runs the shadow form — same budget,
same tasks, with-records vs without-records — and reports the mean and cost
difference over process metrics.

裁决口径 (before 点名裁决 1 / test 位 is decided): only process metrics are
compared — gate pass rate, tool reuse rate, cost. The conclusion can only say
"records changed the improvement behavior". A val-score comparison would
promote val from "gate-read" to "verdict-read" (and re-fit val over multiple
ablations) — the very thing SelfSearch refuses to do with dev-score selection.

记录无信号 → 本阶段判负并停 (no signal → the stage is judged failed and stops).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final

from evolver.experiment.agent_runner import TaskResult
from evolver.experiment.metrics import compare_metrics, compute_metrics
from evolver.experiment.stats import MIN_N

#: Marker a stub agent looks for in the context to simulate the record effect.
#: Defaults to the episode-block heading the real renderer emits, so a stub
#: and a real record context agree on what "has a record" means.
RECORD_MARKER: Final = "## Previous Episode"


def make_stub_agent(*, record_effect: bool = True, record_marker: str = RECORD_MARKER) -> Any:
    """A stub agent ``(prompt, context) -> (answer, tokens)``.

    Simulates the record effect: succeeds when the context carries the record
    marker. With ``record_effect=False`` the marker is ignored (the null
    condition — records change nothing), which is how the no-signal path is
    exercised.
    """

    def agent(prompt: str, context: str) -> tuple[str, int]:
        has_record = record_marker in context
        success = has_record if record_effect else False
        return ("solved" if success else "unsolved"), 100

    return agent


def _run_one(
    task: dict[str, Any],
    *,
    record_context: str,
    agent_fn: Any,
    success_mode: str = "exact",
    arm: str = "",
    on_task_error: Callable[[str, str, str], None] | None = None,
) -> TaskResult:
    task_id = str(task.get("id", "unknown"))
    prompt = str(task.get("prompt", ""))
    try:
        answer, tokens = agent_fn(prompt, record_context)
    except Exception as exc:
        # One failed LLM call must not kill the whole ablation: the task
        # counts as failed and the error rides along for the report.
        if on_task_error is not None:
            on_task_error(task_id, arm, str(exc))
        return TaskResult(task_id=task_id, success=False, answer="", tokens_used=0)
    expected = task.get("expected")
    if expected:
        success = expected in answer if success_mode == "contains" else answer == expected
    else:
        success = bool(answer)
    return TaskResult(
        task_id=task_id,
        success=success,
        answer=answer,
        tokens_used=tokens,
    )


#: Neutral filler for the placebo control arm. It must never contain the
#: record marker or any episode content — it only occupies the system slot.
_PLACEBO_UNIT: Final = "## Note\nThis block intentionally carries no prior-episode information.\n"


def make_placebo_context(record_context: str) -> str:
    """A neutral context of the same length as *record_context*.

    With an empty control context the without-records arm sends no system
    message at all, so the two arms differ by "has a system role" as well as
    "has a record". A placebo of equal length isolates the record content.
    Returns ``""`` when there is no record context to match.
    """
    n = len(record_context)
    if n == 0:
        return ""
    reps = n // len(_PLACEBO_UNIT) + 1
    return (_PLACEBO_UNIT * reps)[:n]


def run_ablation(
    tasks: list[dict[str, Any]],
    *,
    record_context: str,
    agent_fn: Any,
    budget: int | None = None,
    success_mode: str = "exact",
    on_task_error: Callable[[str, str, str], None] | None = None,
    control_context: str = "",
) -> dict[str, Any]:
    """Run the with-records vs without-records ablation over the same tasks.

    Same budget (same tasks, same agent), two conditions. Returns the metrics
    for both + the comparison. Process metrics only (see module docstring) —
    the verdict is about whether records changed the improvement behavior,
    not about downstream task scores.

    *success_mode* controls how a task's ``expected`` is checked: ``"exact"``
    (the answer equals it — for deterministic agents) or ``"contains"`` (the
    answer includes it — for LLM-generated code, where an exact match is
    neither possible nor the point).

    *on_task_error* is called as ``(task_id, arm, error)`` when an agent call
    raises; the task counts as failed and the run continues.

    *control_context* is what the without-records arm sends (default ``""``:
    no system message). Pass :func:`make_placebo_context` to keep the system
    slot occupied in both arms so only the record content differs.
    """
    selected = list(tasks[:budget]) if budget else list(tasks)
    with_results = [
        _run_one(
            t,
            record_context=record_context,
            agent_fn=agent_fn,
            success_mode=success_mode,
            arm="with_records",
            on_task_error=on_task_error,
        )
        for t in selected
    ]
    without_results = [
        _run_one(
            t,
            record_context=control_context,
            agent_fn=agent_fn,
            success_mode=success_mode,
            arm="without_records",
            on_task_error=on_task_error,
        )
        for t in selected
    ]
    with_metrics = compute_metrics(with_results)
    without_metrics = compute_metrics(without_results)
    return {
        "with_records": with_metrics,
        "without_records": without_metrics,
        "comparison": compare_metrics(without_metrics, with_metrics),
        "budget": len(selected),
        "control": "placebo" if control_context else "empty",
    }


def ablation_verdict(report: dict[str, Any]) -> dict[str, Any]:
    """The verdict: signal / no-signal, over process metrics only.

    记录无信号 → 判负并停. Before 点名裁决 1, only process metrics decide.

    The verdict itself is unchanged (a signal is a signal), but it now carries
    how much weight it can bear: ``sample_adequate`` (both arms reach
    :data:`~evolver.experiment.stats.MIN_N`), ``signal_basis`` (a tokens-only
    tie-break is not a success-rate gain), and ``control`` (empty vs placebo).
    An under-powered signal is indicative only and the conclusion says so.
    """
    comparison = report.get("comparison", {})
    signal = bool(comparison.get("evolved_better", False))
    n_with = int(report.get("with_records", {}).get("total", 0))
    n_without = int(report.get("without_records", {}).get("total", 0))
    n_per_arm = min(n_with, n_without)
    adequate = n_per_arm >= MIN_N
    if not signal:
        basis = "none"
    elif float(comparison.get("success_rate_delta", 0.0)) > 0:
        basis = "success_rate"
    else:
        basis = "tokens_only"
    conclusion = (
        "records changed the improvement behavior"
        if signal
        else "no signal — the stage is judged failed and stops"
    )
    if signal and not adequate:
        conclusion += f" (indicative only: n={n_per_arm} per arm < {MIN_N})"
    if basis == "tokens_only":
        conclusion += " (tokens-only: success rate did not move)"
    return {
        "signal": signal,
        "verdict": "signal" if signal else "no_signal",
        "conclusion": conclusion,
        "metrics": (
            "process_only (success rate, token cost; "
            "gate pass rate and tool reuse are not measured here)"
        ),
        "n_per_arm": n_per_arm,
        "sample_adequate": adequate,
        "signal_basis": basis,
        "control": str(report.get("control", "empty")),
    }


__all__ = [
    "RECORD_MARKER",
    "ablation_verdict",
    "make_placebo_context",
    "make_stub_agent",
    "run_ablation",
]
