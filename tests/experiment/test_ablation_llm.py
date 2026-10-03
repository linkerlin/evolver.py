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


def test_ablation_cli_placebo_flag_controls_the_without_arm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from evolver.experiment import cli as exp_cli

    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(json.dumps(_tasks()), encoding="utf-8")
    seen: list[dict[str, Any]] = []

    def fake_run(tasks: list[dict[str, Any]], context: str, **kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs)
        return {
            "model_requested": kwargs.get("model"),
            "server_models": [],
            "budget": len(tasks),
            "with_records": {"successes": 0, "total": 2, "total_tokens": 0},
            "without_records": {"successes": 0, "total": 2, "total_tokens": 0},
            "comparison": {"success_rate_pct": "+0.0%", "token_delta_pct": "+0.0%"},
            "verdict": {"verdict": "no_signal", "conclusion": "none"},
            "errors": [],
        }

    monkeypatch.setattr(ablation_llm, "run_llm_ablation", fake_run)
    record = "## Previous Episode\n- x"
    base = ["--tasks", str(tasks_file), "--ablation", "--record-context", record]
    assert exp_cli.main(base) == 0
    assert exp_cli.main([*base, "--placebo"]) == 0
    assert seen[0]["control_context"] == ""
    assert len(seen[1]["control_context"]) == len(record)
    assert "Previous Episode" not in seen[1]["control_context"]


# ---------------------------------------------------------------------------
# --from-episodes: the store-to-ablation bridge (no hand-carried file)
# ---------------------------------------------------------------------------


def _episode_scene(run_id: str, event_id: str) -> dict[str, Any]:
    return {
        "event": {
            "type": "EvolutionEvent",
            "id": event_id,
            "run_id": run_id,
            "timestamp": "2026-10-02T00:00:00.000Z",
            "gene_id": "gene_a",
            "mutation": {"id": "mut_1", "category": "repair"},
            "diff_snapshot": "--- a.py\n+++ b.py\n-x = 1\n+x = 2\n",
            "outcome": {"status": "success", "score": 1.0},
            "blast_radius": {"files": 1, "lines": 4},
        },
        "validation_result": {"ok": True, "results": []},
        "fitness_verdict": None,
        "gate": {"accepted": True, "reason": "improved"},
    }


def _record_two_episodes() -> list[str]:
    from evolver.gep import episode_record

    ids: list[str] = []
    for i in (1, 2):
        body = episode_record.build_episode(_episode_scene(f"run_{i}", f"evt_{i}"))
        ids.append(str(episode_record.record_episode(body)["id"]))
    return ids


def test_from_episodes_uses_the_shared_renderer(temp_workspace: Path) -> None:
    """The bridge renders with the dispatch renderer, not a second format."""
    from evolver.experiment import cli as exp_cli

    ids = _record_two_episodes()
    context, used = exp_cli.build_record_context_from_episodes(limit=2)
    assert used == ids  # recording order, oldest first
    assert context.count("## Previous Episode") == 2
    for ep_id in ids:
        assert ep_id in context


def test_from_episodes_defaults_to_the_latest(temp_workspace: Path) -> None:
    """Default limit 1 matches dispatch (the previous round's record)."""
    from evolver.experiment import cli as exp_cli

    ids = _record_two_episodes()
    context, used = exp_cli.build_record_context_from_episodes()
    assert used == [ids[-1]]
    assert ids[-1] in context


def test_from_episodes_empty_store_is_empty_not_an_error(temp_workspace: Path) -> None:
    """No episodes → ("", []); the CLI says so on stderr, never guesses."""
    from evolver.experiment import cli as exp_cli

    assert exp_cli.build_record_context_from_episodes() == ("", [])


def test_episode_id_pins_one_record(temp_workspace: Path) -> None:
    from evolver.experiment import cli as exp_cli

    ids = _record_two_episodes()
    context, used = exp_cli.build_record_context_from_episodes(episode_id=ids[0])
    assert used == [ids[0]]
    assert ids[0] in context
    assert ids[1] not in context


def test_episode_id_missing_is_empty(temp_workspace: Path) -> None:
    from evolver.experiment import cli as exp_cli

    assert exp_cli.build_record_context_from_episodes(episode_id="sha256:dead") == ("", [])


def test_cli_from_episodes_reports_provenance(
    tmp_path: Path, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--from-episodes` reaches the runner; the report names its source."""
    from evolver.experiment import cli as exp_cli

    ids = _record_two_episodes()
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(json.dumps(_tasks()), encoding="utf-8")
    out_file = tmp_path / "out.json"
    seen: dict[str, Any] = {}

    def fake_run(tasks: list[dict[str, Any]], context: str, **kwargs: Any) -> dict[str, Any]:
        seen["context"] = context
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

    monkeypatch.setattr(ablation_llm, "run_llm_ablation", fake_run)
    rc = exp_cli.main(
        [
            "--tasks",
            str(tasks_file),
            "--ablation",
            "--from-episodes",
            "--output",
            str(out_file),
        ]
    )
    assert rc == 0
    assert "## Previous Episode" in seen["context"]
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved["record_context_source"] == "episodes"
    assert saved["episodes_used"] == [ids[-1]]
    assert saved["record_context_chars"] == len(seen["context"])


def test_cli_file_wins_over_from_episodes(
    tmp_path: Path, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Precedence file > store: the most explicit source wins and is named."""
    from evolver.experiment import cli as exp_cli

    _record_two_episodes()
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(json.dumps(_tasks()), encoding="utf-8")
    ctx_file = tmp_path / "ctx.txt"
    ctx_file.write_text("FILE-CONTEXT", encoding="utf-8")
    out_file = tmp_path / "out.json"
    seen: dict[str, Any] = {}

    def fake_run(tasks: list[dict[str, Any]], context: str, **kwargs: Any) -> dict[str, Any]:
        seen["context"] = context
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

    monkeypatch.setattr(ablation_llm, "run_llm_ablation", fake_run)
    rc = exp_cli.main(
        [
            "--tasks",
            str(tasks_file),
            "--ablation",
            "--record-context-file",
            str(ctx_file),
            "--from-episodes",
            "--output",
            str(out_file),
        ]
    )
    assert rc == 0
    assert seen["context"] == "FILE-CONTEXT"
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved["record_context_source"] == "file"
    assert saved["episodes_used"] == []


def test_cli_rejects_nonpositive_episode_budgets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--episodes-limit/--episode-max-chars < 1 is exit 2, not a silent clamp."""
    from evolver.experiment import cli as exp_cli

    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(json.dumps(_tasks()), encoding="utf-8")

    def fake_run(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("must not run with a bad budget")

    monkeypatch.setattr(ablation_llm, "run_llm_ablation", fake_run)
    assert (
        exp_cli.main(
            ["--tasks", str(tasks_file), "--ablation", "--from-episodes", "--episodes-limit", "0"]
        )
        == 2
    )
    assert (
        exp_cli.main(
            [
                "--tasks",
                str(tasks_file),
                "--ablation",
                "--from-episodes",
                "--episode-max-chars",
                "0",
            ]
        )
        == 2
    )
    assert "must be >= 1" in capsys.readouterr().err
