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
    agent = lambda prompt, context: ("```python\ndef f():\n    pass\n```", 10)
    report = ablation.run_ablation(
        tasks, record_context="", agent_fn=agent, success_mode="contains"
    )
    assert report["with_records"]["success_rate"] == 1.0
    # exact mode would fail (the answer is not exactly "def f")
    exact = ablation.run_ablation(tasks, record_context="", agent_fn=agent)
    assert exact["with_records"]["success_rate"] == 0.0
