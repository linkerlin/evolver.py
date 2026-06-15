"""Tests for the experiment framework."""

from __future__ import annotations

from evolver.experiment.agent_runner import TaskResult, run_task
from evolver.experiment.comparison import run_comparison, run_multi_config
from evolver.experiment.metrics import compare_metrics, compute_metrics, format_report


def _stub_agent(_prompt: str, context: str) -> tuple[str, int]:
    """Stub agent: returns context-influenced answer."""
    if context:
        return "evolved answer with gene", 500
    return "baseline answer", 1000


class TestAgentRunner:
    def test_run_baseline(self) -> None:
        task = {"id": "t1", "prompt": "solve this", "expected": "answer"}
        result = run_task(task, genes=None, agent_fn=_stub_agent)
        assert result.task_id == "t1"
        assert result.tokens_used == 1000
        assert not result.gene_ids

    def test_run_with_genes(self) -> None:
        task = {"id": "t1", "prompt": "solve this", "expected": "gene"}
        genes = [{"id": "g1", "summary": "test gene", "strategy": ["step1"]}]
        result = run_task(task, genes=genes, agent_fn=_stub_agent)
        assert result.gene_ids == ["g1"]
        assert result.tokens_used == 500
        assert result.success  # "gene" is in "evolved answer with gene"

    def test_no_agent_returns_error(self) -> None:
        task = {"id": "t1", "prompt": "solve"}
        result = run_task(task, genes=None, agent_fn=None)
        assert not result.success
        assert result.error == "no_agent_fn"

    def test_check_success_expected_string(self) -> None:
        task = {"id": "t1", "prompt": "p", "expected": "42"}
        result = run_task(task, agent_fn=lambda _p, _c: ("the answer is 42", 10))
        assert result.success

    def test_check_success_no_expected(self) -> None:
        task = {"id": "t1", "prompt": "p"}
        result = run_task(task, agent_fn=lambda _p, _c: ("some answer", 10))
        assert result.success


class TestMetrics:
    def test_empty(self) -> None:
        m = compute_metrics([])
        assert m["total"] == 0
        assert m["success_rate"] == 0.0

    def test_basic(self) -> None:
        results = [
            TaskResult(task_id="t1", success=True, tokens_used=100, latency_s=1.0),
            TaskResult(task_id="t2", success=False, tokens_used=200, latency_s=2.0),
        ]
        m = compute_metrics(results)
        assert m["total"] == 2
        assert m["successes"] == 1
        assert m["success_rate"] == 0.5
        assert m["avg_tokens"] == 150.0

    def test_compare_better(self) -> None:
        baseline = {"success_rate": 0.3, "avg_tokens": 1000, "total": 10}
        evolved = {"success_rate": 0.6, "avg_tokens": 800, "total": 10}
        comp = compare_metrics(baseline, evolved)
        assert comp["success_rate_delta"] == 0.3
        assert comp["evolved_better"] is True

    def test_compare_worse(self) -> None:
        baseline = {"success_rate": 0.8, "avg_tokens": 500, "total": 10}
        evolved = {"success_rate": 0.5, "avg_tokens": 600, "total": 10}
        comp = compare_metrics(baseline, evolved)
        assert comp["evolved_better"] is False

    def test_format_report(self) -> None:
        baseline = {
            "success_rate": 0.3, "avg_tokens": 1000,
            "avg_latency_s": 5.0, "total": 10, "successes": 3,
        }
        evolved = {
            "success_rate": 0.6, "avg_tokens": 800,
            "avg_latency_s": 3.0, "total": 10, "successes": 6,
        }
        comp = compare_metrics(baseline, evolved)
        report = format_report(baseline, evolved, comp)
        assert "EVOLUTION EXPERIMENT REPORT" in report
        assert "EVOLVED WINS" in report


class TestComparison:
    def test_run_comparison(self) -> None:
        tasks = [
            {"id": "t1", "prompt": "p1", "expected": "answer"},
            {"id": "t2", "prompt": "p2", "expected": "answer"},
        ]
        genes = [{"id": "g1", "summary": "gene", "strategy": ["step"]}]
        result = run_comparison(tasks, genes=genes, agent_fn=_stub_agent)
        assert result["baseline_metrics"]["total"] == 2
        assert result["evolved_metrics"]["total"] == 2
        assert "report" in result

    def test_run_multi_config(self) -> None:
        tasks = [{"id": "t1", "prompt": "p", "expected": "answer"}]
        configs = {
            "baseline": None,
            "evolved": [{"id": "g1", "summary": "gene", "strategy": ["step"]}],
        }
        result = run_multi_config(tasks, configs, agent_fn=_stub_agent)
        assert "baseline" in result
        assert "evolved" in result
        assert result["baseline"]["metrics"]["total"] == 1
