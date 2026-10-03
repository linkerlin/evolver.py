"""Ablation adjudication (经验即证据 §5.8) — the stage exit.

SelfSearch's ablation: does giving the improver access to previous episode
records improve outcomes? This module runs the shadow form — same budget,
same tasks, with-records vs without-records — and reports the mean and cost
difference over process metrics.

裁决口径 (点名裁决 1, 2026-10-03): only the metrics this module actually
computes are compared — success rate and token cost. Gate pass rate and tool
reuse are not measured here. The conclusion can only say "records changed
the improvement behavior". A val-score comparison would promote val from
"gate-read" to "verdict-read".

n < MIN_N: both signal and no_signal are indicative only. An under-powered
no_signal does not judge the stage failed and does not stop it. A no_signal
at n >= MIN_N does: the stage is judged failed and stops.

``run_stage_exit`` is the machine-checkable form of the same comparison:
seeded AB/BA interleaving (no fixed arm order), per-call records, a paired
exact test over per-task outcomes, and :func:`stage_exit_verdict`, which
refuses a stage conclusion unless every precondition (real episodes, placebo
control, unique tasks, known commit, replayable report) is evidenced.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from collections.abc import Callable, Mapping
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
    seq: int = -1,
    on_task_error: Callable[[str, str, str], None] | None = None,
) -> TaskResult:
    task_id = str(task.get("id", "unknown"))
    prompt = str(task.get("prompt", ""))
    start = time.perf_counter()
    try:
        answer, tokens = agent_fn(prompt, record_context)
    except Exception as exc:
        # One failed LLM call must not kill the whole ablation: the task
        # counts as failed and the error rides along for the report.
        message = str(exc)
        if on_task_error is not None:
            on_task_error(task_id, arm, message)
        return TaskResult(
            task_id=task_id,
            success=False,
            answer="",
            tokens_used=0,
            latency_s=round(time.perf_counter() - start, 4),
            arm=arm,
            seq=seq,
            error=message[:300],
            error_class=classify_error(message),
        )
    total, prompt_tokens, output_tokens = _coerce_usage(tokens)
    expected = task.get("expected")
    if expected:
        success = expected in answer if success_mode == "contains" else answer == expected
    else:
        success = bool(answer)
    return TaskResult(
        task_id=task_id,
        success=success,
        answer=answer,
        tokens_used=total,
        latency_s=round(time.perf_counter() - start, 4),
        arm=arm,
        seq=seq,
        prompt_tokens=prompt_tokens,
        output_tokens=output_tokens,
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
    seq = 0
    with_results = []
    for t in selected:
        with_results.append(
            _run_one(
                t,
                record_context=record_context,
                agent_fn=agent_fn,
                success_mode=success_mode,
                arm="with_records",
                seq=seq,
                on_task_error=on_task_error,
            )
        )
        seq += 1
    without_results = []
    for t in selected:
        without_results.append(
            _run_one(
                t,
                record_context=control_context,
                agent_fn=agent_fn,
                success_mode=success_mode,
                arm="without_records",
                seq=seq,
                on_task_error=on_task_error,
            )
        )
        seq += 1
    with_metrics = compute_metrics(with_results)
    without_metrics = compute_metrics(without_results)
    return {
        "with_records": with_metrics,
        "without_records": without_metrics,
        "comparison": compare_metrics(without_metrics, with_metrics),
        "budget": len(selected),
        "control": "placebo" if control_context else "empty",
    }


def _coerce_usage(tokens: Any) -> tuple[int, int, int]:
    """Split an agent's token report into ``(total, prompt, output)``.

    The agent protocol returns ``(answer, tokens)`` where *tokens* is either
    an int total (stubs, older agents) or a usage mapping with
    ``total_tokens``/``prompt_tokens``/``completion_tokens`` (the real LLM
    client). Anything else coerces to zeros — a missing split is reported as
    unmeasured, never guessed.
    """
    if isinstance(tokens, bool):
        return (0, 0, 0)
    if isinstance(tokens, int):
        return (max(0, tokens), 0, 0)
    if isinstance(tokens, Mapping):

        def _num(*keys: str) -> int:
            for key in keys:
                try:
                    value = int(tokens.get(key, 0) or 0)
                except (TypeError, ValueError):
                    continue
                return max(0, value)
            return 0

        return (
            _num("total_tokens"),
            _num("prompt_tokens"),
            _num("completion_tokens", "output_tokens"),
        )
    return (0, 0, 0)


_ERROR_HTTP_RE: Final = re.compile(r"LLM HTTP (\d{3})")


def classify_error(message: str) -> str:
    """Map a call failure to a stable, countable error class.

    The classes are the failure shapes :class:`DeepSeekClient` actually
    produces; anything unrecognized is ``"other"`` rather than dropped.
    """
    msg = message or ""
    if "no DEEPSEEK_API_KEY" in msg:
        return "no_key"
    http = _ERROR_HTTP_RE.search(msg)
    if http:
        return f"http_{http.group(1)}"
    lowered = msg.lower()
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "malformed LLM response" in msg:
        return "malformed"
    if "empty answer" in msg:
        return "empty_answer"
    if "LLM request failed" in msg:
        return "network"
    return "other"


def check_task_set(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate the ablation task set: non-empty ids, no duplicates.

    A repeated task id would run one task twice and count it twice — a
    silent sample-size inflation. Raises :class:`ValueError` naming the
    offending id instead.
    """
    seen: set[str] = set()
    for task in tasks:
        raw_id = task.get("id", "") if isinstance(task, Mapping) else ""
        task_id = str(raw_id).strip()
        if not task_id:
            raise ValueError("stage-exit task ids must be non-empty")
        if task_id in seen:
            raise ValueError(f"duplicate stage-exit task id: {task_id!r}")
        seen.add(task_id)
    return list(tasks)


def task_digest(tasks: list[dict[str, Any]]) -> str:
    """Content hash of the task set, in execution-input order.

    Binds the report to exactly the tasks that ran: same digest ⇒ same
    (id, prompt, expected) sequence. Order matters — a reordered rerun is a
    different digest, honestly so.
    """
    canonical = [
        {
            "id": str(t.get("id", "")),
            "prompt": str(t.get("prompt", "")),
            "expected": t.get("expected"),
        }
        for t in tasks
    ]
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=True, default=str)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _paired_outcomes(
    with_results: list[TaskResult], without_results: list[TaskResult]
) -> dict[str, Any]:
    """Paired exact test over the per-task outcomes (a = with_records).

    Reuses the bench paired comparison (:func:`bench.compare.compare_runs`):
    same task set, discordant pairs only, direction AND p-value required.
    Imported lazily — the bench package is heavy and the experiment runner
    stays import-light.
    """
    from evolver.bench.compare import compare_runs

    by_id = {r.task_id: r for r in without_results}
    with_per = [{"id": r.task_id, "score": 1.0 if r.success else 0.0} for r in with_results]
    without_per = [
        {"id": r.task_id, "score": 1.0 if by_id[r.task_id].success else 0.0} for r in with_results
    ]
    result = compare_runs({"per_task": with_per}, {"per_task": without_per})
    result["favors"] = (
        "with_records"
        if result["verdict"] == "a_better"
        else "without_records"
        if result["verdict"] == "b_better"
        else "neither"
    )
    return result


def _prompt_balance(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Server-reported prompt-token balance between the arms.

    Char-equal placebo is not token-equal: the provider tokenizes the two
    contexts differently. When neither arm reports a usage split the balance
    is ``unreported``, not zero.
    """
    with_avg, without_avg = 0.0, 0.0
    for key, arm in (("with_avg", "with_records"), ("without_avg", "without_records")):
        values = [float(c.get("prompt_tokens", 0)) for c in calls if c.get("arm") == arm]
        avg = sum(values) / len(values) if values else 0.0
        if key == "with_avg":
            with_avg = avg
        else:
            without_avg = avg
    if with_avg == 0.0 and without_avg == 0.0:
        return {
            "status": "unreported (no usage split from the agent)",
            "with_avg_prompt_tokens": 0.0,
            "without_avg_prompt_tokens": 0.0,
            "delta_pct": None,
        }
    delta = (with_avg - without_avg) / without_avg if without_avg else None
    return {
        "status": "measured",
        "with_avg_prompt_tokens": round(with_avg, 1),
        "without_avg_prompt_tokens": round(without_avg, 1),
        "delta_pct": round(delta, 4) if delta is not None else None,
    }


def run_stage_exit(
    tasks: list[dict[str, Any]],
    *,
    record_context: str,
    agent_fn: Any,
    budget: int | None = None,
    success_mode: str = "exact",
    on_task_error: Callable[[str, str, str], None] | None = None,
    control_context: str = "",
    order_seed: int = 0,
) -> dict[str, Any]:
    """The stage-exit ablation: same tasks, seeded AB/BA interleaving.

    Unlike :func:`run_ablation` (with-arm batch first, then control batch),
    each task's two arms run back-to-back in an order drawn from a seeded RNG,
    so cache, throttling, or provider drift cannot systematically favor one
    arm. Every call lands in ``calls`` with its sequence number, arm, outcome,
    latency, usage split, and error class; ``paired`` carries the exact
    paired test over the per-task outcomes; ``task_digest`` binds the report
    to the task content that ran.
    """
    selected = check_task_set(tasks)
    if budget:
        selected = selected[:budget]
    rng = random.Random(order_seed)
    plan: list[tuple[dict[str, Any], str]] = []
    for task in selected:
        arms = ["with_records", "without_records"]
        rng.shuffle(arms)
        for arm in arms:
            plan.append((task, arm))
    by_task: dict[str, dict[str, TaskResult]] = {}
    calls: list[dict[str, Any]] = []
    for seq, (task, arm) in enumerate(plan):
        context = record_context if arm == "with_records" else control_context
        result = _run_one(
            task,
            record_context=context,
            agent_fn=agent_fn,
            success_mode=success_mode,
            arm=arm,
            seq=seq,
            on_task_error=on_task_error,
        )
        by_task.setdefault(result.task_id, {})[arm] = result
        calls.append(
            {
                "seq": result.seq,
                "arm": result.arm,
                "task_id": result.task_id,
                "success": result.success,
                "latency_s": result.latency_s,
                "tokens_used": result.tokens_used,
                "prompt_tokens": result.prompt_tokens,
                "output_tokens": result.output_tokens,
                "error_class": result.error_class,
                "server_model": "",
            }
        )
    with_results = [by_task[str(t.get("id", "")).strip()]["with_records"] for t in selected]
    without_results = [by_task[str(t.get("id", "")).strip()]["without_records"] for t in selected]
    with_metrics = compute_metrics(with_results)
    without_metrics = compute_metrics(without_results)
    return {
        "with_records": with_metrics,
        "without_records": without_metrics,
        "comparison": compare_metrics(without_metrics, with_metrics),
        "budget": len(selected),
        "control": "placebo" if control_context else "empty",
        "order_seed": order_seed,
        "task_digest": task_digest(selected),
        "schedule": [
            {"seq": seq, "arm": arm, "task_id": str(task.get("id", "")).strip()}
            for seq, (task, arm) in enumerate(plan)
        ],
        "calls": calls,
        "paired": _paired_outcomes(with_results, without_results),
        "prompt_token_balance": _prompt_balance(calls),
    }


def check_stage_eligibility(evidence: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Machine-check the stage-exit preconditions.

    The charter's prohibitions (no inline/file context, no repeated tasks, no
    empty episodes, placebo control, replayable report) become unreachable
    states here instead of documentation: every missing precondition is named
    in ``reasons`` and the report is ineligible.
    """
    reasons: list[str] = []
    if not (evidence.get("episodes_used") or []):
        reasons.append("stage-exit needs real episodes: episodes_used is empty")
    if str(evidence.get("control") or "") != "placebo":
        reasons.append(
            f"stage-exit needs --placebo: control is {str(evidence.get('control') or '')!r}"
        )
    if not evidence.get("tasks_unique"):
        reasons.append("stage-exit needs unique non-empty task ids")
    if not str(evidence.get("task_digest") or ""):
        reasons.append("stage-exit needs a task-set digest")
    if not str(evidence.get("commit") or ""):
        reasons.append("stage-exit needs a known code commit")
    if not str(evidence.get("report_path") or ""):
        reasons.append("stage-exit needs --output: the report must land on disk to be replayable")
    return (not reasons, reasons)


def stage_exit_verdict(report: Mapping[str, Any]) -> dict[str, Any]:
    """The stage-exit verdict: eligibility first, then the weighted signal.

    ``stage`` is one of ``ineligible`` / ``inconclusive`` / ``positive`` /
    ``negative-stop``. A positive stage needs ALL of: eligibility, adequate
    samples, a success-rate (not tokens-only) basis, and a paired test that
    favors the with-records arm. ``stage_stop`` is true only for an eligible,
    adequate no_signal — the charter's stop rule, now machine-checked.
    """
    base = ablation_verdict(report)
    evidence = report.get("stage_exit_evidence")
    if not isinstance(evidence, Mapping):
        evidence = {}
    eligible, reasons = check_stage_eligibility(evidence)
    paired = report.get("paired")
    if not isinstance(paired, Mapping):
        paired = {}
    if not eligible:
        stage = "ineligible"
    elif not base["sample_adequate"] or base["signal_basis"] == "tokens_only":
        stage = "inconclusive"
    elif not base["signal"]:
        stage = "negative-stop"
    elif base["signal_basis"] == "success_rate" and paired.get("verdict") == "a_better":
        stage = "positive"
    else:
        stage = "inconclusive"
    return {
        **base,
        "eligible": eligible,
        "eligibility_reasons": reasons,
        "stage": stage,
        "stage_stop": stage == "negative-stop",
        "paired": dict(paired),
    }


def ablation_verdict(report: Mapping[str, Any]) -> dict[str, Any]:
    """The verdict: signal / no-signal, over process metrics only.

    记录无信号 → 判负并停. Before 点名裁决 1, only process metrics decide.

    The verdict itself is unchanged (a signal is a signal), but it now carries
    how much weight it can bear: ``sample_adequate`` (both arms reach
    :data:`~evolver.experiment.stats.MIN_N`), ``signal_basis`` (a tokens-only
    tie-break is not a success-rate gain), ``control`` (empty vs placebo),
    and ``stage_stop`` (true only for an adequate no_signal). An under-powered
    result, signal or not, is indicative only and does not stop the stage.
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
    conclusion = "records changed the improvement behavior" if signal else "no signal"
    stage_stop = (not signal) and adequate
    if not adequate:
        conclusion += f" (indicative only: n={n_per_arm} per arm < {MIN_N})"
    elif not signal:
        conclusion += " — the stage is judged failed and stops"
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
        "stage_stop": stage_stop,
        "signal_basis": basis,
        "control": str(report.get("control", "empty")),
    }


__all__ = [
    "RECORD_MARKER",
    "ablation_verdict",
    "check_stage_eligibility",
    "check_task_set",
    "classify_error",
    "make_placebo_context",
    "make_stub_agent",
    "run_ablation",
    "run_stage_exit",
    "stage_exit_verdict",
    "task_digest",
]
