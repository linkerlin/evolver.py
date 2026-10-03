"""Tests for evolver.experiment.ablation (经验即证据 §5.8 — the stage exit).

The ablation adjudication: with-records vs without-records over the same
budget and tasks, reporting the mean and cost difference over process
metrics. 记录无信号 → 判负并停.
"""

from __future__ import annotations

from evolver.experiment import ablation


def _tasks(n: int = 4) -> list[dict[str, object]]:
    return [{"id": f"t{i}", "prompt": f"task {i}", "expected": "solved"} for i in range(n)]


def test_with_records_beats_without_when_the_record_has_effect() -> None:
    """判据: 可复算的对照报告 — with > over without when records help."""
    report = ablation.run_ablation(
        _tasks(),
        record_context="## Previous Episode\n" + ablation.RECORD_MARKER + "\n- gene_a",
        agent_fn=ablation.make_stub_agent(record_effect=True),
    )
    assert report["budget"] == 4
    assert report["with_records"]["success_rate"] == 1.0
    assert report["without_records"]["success_rate"] == 0.0
    verdict = ablation.ablation_verdict(report)
    assert verdict["signal"] is True
    assert verdict["verdict"] == "signal"
    assert "changed the improvement behavior" in verdict["conclusion"]


def test_no_signal_when_records_change_nothing() -> None:
    """记录无信号 → 判负并停."""
    report = ablation.run_ablation(
        _tasks(),
        record_context="## Previous Episode\n" + ablation.RECORD_MARKER,
        agent_fn=ablation.make_stub_agent(record_effect=False),
    )
    assert report["with_records"]["success_rate"] == 0.0
    assert report["without_records"]["success_rate"] == 0.0
    verdict = ablation.ablation_verdict(report)
    assert verdict["signal"] is False
    assert verdict["verdict"] == "no_signal"
    assert "judged failed and stops" in verdict["conclusion"]


def test_budget_caps_both_conditions_equally() -> None:
    """同预算: both conditions run the same number of tasks."""
    report = ablation.run_ablation(
        _tasks(10),
        record_context=ablation.RECORD_MARKER,
        agent_fn=ablation.make_stub_agent(),
        budget=3,
    )
    assert report["budget"] == 3
    assert report["with_records"]["total"] == 3
    assert report["without_records"]["total"] == 3


def test_cost_difference_is_reported() -> None:
    """报告均值与成本差 (process metrics)."""
    report = ablation.run_ablation(
        _tasks(),
        record_context=ablation.RECORD_MARKER,
        agent_fn=ablation.make_stub_agent(),
    )
    comp = report["comparison"]
    assert "success_rate_delta" in comp
    assert "token_delta_pct" in comp


def test_contains_success_mode_for_llm_output() -> None:
    """LLM-generated code is checked by containment, not exact match."""
    tasks = [{"id": "t1", "prompt": "write f", "expected": "def f"}]

    def agent(prompt: str, context: str) -> tuple[str, int]:
        return ("```python\ndef f():\n    pass\n```", 10)

    report = ablation.run_ablation(
        tasks, record_context="", agent_fn=agent, success_mode="contains"
    )
    assert report["with_records"]["success_rate"] == 1.0
    # exact mode would fail (the answer is not exactly "def f")
    exact = ablation.run_ablation(tasks, record_context="", agent_fn=agent)
    assert exact["with_records"]["success_rate"] == 0.0


def test_agent_error_counts_as_failure_with_arm() -> None:
    """One raising agent call is a failed task, not a crashed ablation."""
    seen: list[tuple[str, str]] = []

    def bad_agent(prompt: str, context: str) -> tuple[str, int]:
        raise RuntimeError("llm down")

    report = ablation.run_ablation(
        _tasks(2),
        record_context=ablation.RECORD_MARKER,
        agent_fn=bad_agent,
        on_task_error=lambda tid, arm, err: seen.append((tid, arm)),
    )
    assert report["with_records"]["success_rate"] == 0.0
    assert report["without_records"]["success_rate"] == 0.0
    assert sorted(arm for _, arm in seen) == [
        "with_records",
        "with_records",
        "without_records",
        "without_records",
    ]


# ---------------------------------------------------------------------------
# Verdict weight + placebo control (a verdict says how much it can bear)
# ---------------------------------------------------------------------------


def test_small_n_signal_is_marked_indicative_only() -> None:
    """n < MIN_N: still a signal, but the verdict must say it is under-powered."""
    report = ablation.run_ablation(
        _tasks(3),
        record_context=ablation.RECORD_MARKER,
        agent_fn=ablation.make_stub_agent(record_effect=True),
    )
    verdict = ablation.ablation_verdict(report)
    assert verdict["signal"] is True
    assert verdict["n_per_arm"] == 3
    assert verdict["sample_adequate"] is False
    assert verdict["signal_basis"] == "success_rate"
    assert "indicative only" in verdict["conclusion"]


def test_adequate_n_signal_carries_no_caveat() -> None:
    from evolver.experiment.stats import MIN_N

    report = ablation.run_ablation(
        _tasks(MIN_N),
        record_context=ablation.RECORD_MARKER,
        agent_fn=ablation.make_stub_agent(record_effect=True),
    )
    verdict = ablation.ablation_verdict(report)
    assert verdict["sample_adequate"] is True
    assert "indicative only" not in verdict["conclusion"]


def test_tokens_only_signal_is_labelled_as_such() -> None:
    """Equal success rate + fewer tokens is a tie-break, not a success-rate gain."""
    report = {
        "comparison": {"evolved_better": True, "success_rate_delta": 0.0},
        "with_records": {"total": 3},
        "without_records": {"total": 3},
    }
    verdict = ablation.ablation_verdict(report)
    assert verdict["signal"] is True
    assert verdict["signal_basis"] == "tokens_only"
    assert "tokens-only" in verdict["conclusion"]


def test_no_signal_basis_is_none() -> None:
    report = ablation.run_ablation(
        _tasks(),
        record_context=ablation.RECORD_MARKER,
        agent_fn=ablation.make_stub_agent(record_effect=False),
    )
    assert ablation.ablation_verdict(report)["signal_basis"] == "none"


def test_verdict_metrics_claim_only_what_the_code_measures() -> None:
    """The label must not name gate pass rate / tool reuse as measured."""
    report = ablation.run_ablation(
        _tasks(),
        record_context=ablation.RECORD_MARKER,
        agent_fn=ablation.make_stub_agent(),
    )
    label = str(ablation.ablation_verdict(report)["metrics"])
    assert "success rate" in label and "token cost" in label
    assert "not measured" in label


def test_placebo_matches_length_and_carries_no_record_marker() -> None:
    record = "## Previous Episode\n" + ablation.RECORD_MARKER + "\n- gene_a\n" * 40
    placebo = ablation.make_placebo_context(record)
    assert len(placebo) == len(record)
    assert ablation.RECORD_MARKER not in placebo
    assert ablation.make_placebo_context("") == ""


def test_placebo_control_arm_sends_the_placebo_not_nothing() -> None:
    """Both arms occupy the system slot; only the record content differs."""
    seen: dict[str, list[str]] = {"with": [], "without": []}
    record = "## Previous Episode\n" + ablation.RECORD_MARKER

    def agent(prompt: str, context: str) -> tuple[str, int]:
        seen["with" if ablation.RECORD_MARKER in context else "without"].append(context)
        return ("solved" if ablation.RECORD_MARKER in context else "unsolved"), 1

    report = ablation.run_ablation(
        _tasks(2),
        record_context=record,
        agent_fn=agent,
        control_context=ablation.make_placebo_context(record),
    )
    assert report["control"] == "placebo"
    assert all(c == ablation.make_placebo_context(record) for c in seen["without"])
    assert all(len(c) == len(record) for c in seen["with"] + seen["without"])
    assert ablation.ablation_verdict(report)["control"] == "placebo"


def test_default_control_stays_empty() -> None:
    report = ablation.run_ablation(
        _tasks(2),
        record_context=ablation.RECORD_MARKER,
        agent_fn=ablation.make_stub_agent(),
    )
    assert report["control"] == "empty"
