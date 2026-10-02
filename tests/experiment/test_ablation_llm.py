"""Tests for evolver.experiment.ablation_llm (经验即证据 §5.9) — all offline.

The real-LLM wiring is tested with a fake client: no network. What is pinned
here is the honesty contract — the model id is explicit (never inherited from
``DEEPSEEK_MODEL``), the served id is recorded, and an LLM failure is a failed
task, not a crashed run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evolver.experiment import ablation_llm
from evolver.experiment.llm import LLMError


class FakeClient:
    """Stand-in for DeepSeekClient: records how it was built, serves canned text."""

    built: list[FakeClient] = []

    def __init__(
        self, *, model: str | None = None, max_tokens: int = 4096, timeout_s: int = 120
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.api_key = "test-key"
        self.last_server_model = ""
        FakeClient.built.append(self)

    def complete_prompt(
        self, prompt: str, *, context: str = "", max_tokens: int | None = None
    ) -> tuple[str, int]:
        self.last_server_model = "deepseek-flash"
        if "boom" in prompt:
            raise LLMError("boom")
        if "## Previous Episode" in context:
            return ("solved def f", 100)
        return ("unsolved", 100)


class NoKeyClient(FakeClient):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.api_key = ""


@pytest.fixture(autouse=True)
def _fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeClient.built.clear()
    monkeypatch.setattr(ablation_llm, "DeepSeekClient", FakeClient)
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-pro")


def _tasks() -> list[dict[str, Any]]:
    return [
        {"id": "t1", "prompt": "write f", "expected": "def f"},
        {"id": "t2", "prompt": "write g", "expected": "def g"},
    ]


def test_model_pinned_explicitly_ignores_env() -> None:
    ablation_llm.run_llm_ablation(_tasks(), "## Previous Episode\n- x", model="deepseek-flash")
    assert FakeClient.built and FakeClient.built[-1].model == "deepseek-flash"


def test_server_model_recorded_from_provider() -> None:
    report = ablation_llm.run_llm_ablation(_tasks(), "## Previous Episode\n- x")
    assert report["model_requested"] == "deepseek-flash"
    assert report["server_models"] == ["deepseek-flash"]


def test_llm_error_is_a_failed_task_not_a_crashed_run() -> None:
    tasks = [
        {"id": "t-ok", "prompt": "write f", "expected": "def f"},
        {"id": "t-bad", "prompt": "boom write f", "expected": "def f"},
    ]
    report = ablation_llm.run_llm_ablation(tasks, "## Previous Episode\n- x")
    assert report["errors"], "the failed call must be recorded"
    arms = {(e["task_id"], e["arm"]) for e in report["errors"]}
    assert ("t-bad", "with_records") in arms
    assert ("t-bad", "without_records") in arms
    # The good task still ran in both arms.
    assert report["with_records"]["total"] == 2


def test_missing_key_fails_before_any_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ablation_llm, "DeepSeekClient", NoKeyClient)
    with pytest.raises(LLMError):
        ablation_llm.run_llm_ablation(_tasks(), "ctx")


def test_ablation_cli_wires_model_and_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`experiment --ablation` reaches the runner without network."""
    from evolver.experiment import cli as exp_cli

    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(json.dumps(_tasks()), encoding="utf-8")
    out_file = tmp_path / "out.json"
    seen: dict[str, Any] = {}

    def fake_run(tasks: list[dict[str, Any]], context: str, **kwargs: Any) -> dict[str, Any]:
        seen["tasks"] = tasks
        seen["context"] = context
        seen["kwargs"] = kwargs
        return {
            "model_requested": kwargs.get("model"),
            "server_models": ["deepseek-flash"],
            "budget": len(tasks),
            "with_records": {"successes": 1, "total": 2, "total_tokens": 100},
            "without_records": {"successes": 0, "total": 2, "total_tokens": 100},
            "comparison": {
                "success_rate_pct": "+50.0%",
                "token_delta_pct": "+0.0%",
            },
            "verdict": {"verdict": "signal", "conclusion": "changed"},
            "errors": [],
        }

    # _main_ablation imports run_llm_ablation from ablation_llm at call time.
    monkeypatch.setattr(ablation_llm, "run_llm_ablation", fake_run)
    rc = exp_cli.main(
        [
            "--tasks",
            str(tasks_file),
            "--ablation",
            "--record-context",
            "## Previous Episode\n- x",
            "--model",
            "deepseek-flash",
            "--output",
            str(out_file),
        ]
    )
    assert rc == 0
    assert seen["kwargs"]["model"] == "deepseek-flash"
    assert seen["context"] == "## Previous Episode\n- x"
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved["verdict"]["verdict"] == "signal"
    assert "signal" in capsys.readouterr().err
