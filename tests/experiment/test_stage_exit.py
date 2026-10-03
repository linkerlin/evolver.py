"""Tests for the stage-exit ablation contract (关口② — 机器可判定的阶段出口).

The stage exit is not a new capability: it is the existing ablation with the
causal-identification gaps closed — seeded AB/BA interleaving, per-call
records, paired significance, frozen sampling params, and CLI gates that make
an ineligible run unreachable instead of merely undocumented.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evolver.experiment import ablation


def _tasks(n: int = 4) -> list[dict[str, Any]]:
    return [{"id": f"t{i}", "prompt": f"task {i}", "expected": "solved"} for i in range(n)]


def _record_ctx() -> str:
    return "## Previous Episode\n" + ablation.RECORD_MARKER + "\n- gene_a"


# ---------------------------------------------------------------------------
# Seeded interleaving: no fixed arm order
# ---------------------------------------------------------------------------


def test_schedule_runs_both_arms_per_task_with_unique_seqs() -> None:
    report = ablation.run_stage_exit(
        _tasks(4),
        record_context=_record_ctx(),
        agent_fn=ablation.make_stub_agent(),
        control_context=ablation.make_placebo_context(_record_ctx()),
        order_seed=7,
    )
    sched = report["schedule"]
    assert len(sched) == 8
    assert sorted(s["seq"] for s in sched) == list(range(8))
    by_task: dict[str, set[str]] = {}
    for s in sched:
        by_task.setdefault(s["task_id"], set()).add(s["arm"])
    assert all(arms == {"with_records", "without_records"} for arms in by_task.values())
    assert report["order_seed"] == 7


def test_same_seed_reproduces_the_schedule() -> None:
    kw: dict[str, Any] = {
        "record_context": _record_ctx(),
        "agent_fn": ablation.make_stub_agent(),
        "control_context": ablation.make_placebo_context(_record_ctx()),
        "order_seed": 42,
    }
    first = ablation.run_stage_exit(_tasks(5), **kw)["schedule"]
    second = ablation.run_stage_exit(_tasks(5), **kw)["schedule"]
    assert [(s["seq"], s["arm"], s["task_id"]) for s in first] == [
        (s["seq"], s["arm"], s["task_id"]) for s in second
    ]


def test_calls_carry_per_call_records() -> None:
    report = ablation.run_stage_exit(
        _tasks(2),
        record_context=_record_ctx(),
        agent_fn=ablation.make_stub_agent(),
        control_context=ablation.make_placebo_context(_record_ctx()),
        order_seed=1,
    )
    calls = report["calls"]
    assert len(calls) == 4
    for call in calls:
        assert set(call) >= {
            "seq",
            "arm",
            "task_id",
            "success",
            "latency_s",
            "tokens_used",
            "prompt_tokens",
            "output_tokens",
            "error_class",
            "server_model",
        }
        assert call["latency_s"] >= 0.0
        assert call["error_class"] == ""


# ---------------------------------------------------------------------------
# Task-set integrity: unique ids, content-bound digest
# ---------------------------------------------------------------------------


def test_duplicate_task_ids_are_rejected_with_the_id_named() -> None:
    tasks = [*_tasks(2), {"id": "t1", "prompt": "other", "expected": "solved"}]
    with pytest.raises(ValueError, match="t1"):
        ablation.run_stage_exit(
            tasks,
            record_context=_record_ctx(),
            agent_fn=ablation.make_stub_agent(),
            order_seed=0,
        )


def test_blank_task_id_is_rejected() -> None:
    tasks = [{"id": "  ", "prompt": "x"}]
    with pytest.raises(ValueError, match="empty"):
        ablation.run_stage_exit(
            tasks,
            record_context=_record_ctx(),
            agent_fn=ablation.make_stub_agent(),
            order_seed=0,
        )


def test_task_digest_is_stable_and_content_bound() -> None:
    first = ablation.task_digest(_tasks(3))
    assert first.startswith("sha256:") and len(first) == len("sha256:") + 64
    assert ablation.task_digest(_tasks(3)) == first
    changed = _tasks(3)
    changed[1]["prompt"] = "different task"
    assert ablation.task_digest(changed) != first
    reordered = list(reversed(_tasks(3)))
    assert ablation.task_digest(reordered) != first


# ---------------------------------------------------------------------------
# Usage split + error classes
# ---------------------------------------------------------------------------


def test_agent_may_return_a_usage_split() -> None:
    def agent(prompt: str, context: str) -> tuple[str, dict[str, int]]:
        return ("solved", {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12})

    report = ablation.run_stage_exit(
        _tasks(1),
        record_context=_record_ctx(),
        agent_fn=agent,
        order_seed=0,
    )
    for call in report["calls"]:
        assert call["tokens_used"] == 12
        assert call["prompt_tokens"] == 5
        assert call["output_tokens"] == 7


def test_int_tokens_still_work_with_zero_split() -> None:
    report = ablation.run_stage_exit(
        _tasks(1),
        record_context=_record_ctx(),
        agent_fn=ablation.make_stub_agent(),
        order_seed=0,
    )
    assert report["calls"][0]["tokens_used"] == 100
    assert report["calls"][0]["prompt_tokens"] == 0


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("no DEEPSEEK_API_KEY configured", "no_key"),
        ("LLM HTTP 429: rate limited", "http_429"),
        ("LLM HTTP 401: bad key", "http_401"),
        ("LLM request failed: timed out", "timeout"),
        ("malformed LLM response: {...}", "malformed"),
        ("LLM returned empty answer (finish=stop)", "empty_answer"),
        ("LLM request failed: connection reset", "network"),
        ("something entirely new", "other"),
    ],
)
def test_error_classes_are_stable(message: str, expected: str) -> None:
    assert ablation.classify_error(message) == expected


def test_failed_calls_record_their_class() -> None:
    def bad_agent(prompt: str, context: str) -> tuple[str, int]:
        raise RuntimeError("LLM HTTP 429: rate limited")

    report = ablation.run_stage_exit(
        _tasks(1),
        record_context=_record_ctx(),
        agent_fn=bad_agent,
        order_seed=0,
    )
    assert all(c["success"] is False for c in report["calls"])
    assert all(c["error_class"] == "http_429" for c in report["calls"])


# ---------------------------------------------------------------------------
# Paired significance over per-task outcomes
# ---------------------------------------------------------------------------


def test_paired_comparison_is_present_and_honest_on_ties() -> None:
    report = ablation.run_stage_exit(
        _tasks(4),
        record_context=_record_ctx(),
        agent_fn=ablation.make_stub_agent(record_effect=False),
        order_seed=3,
    )
    paired = report["paired"]
    assert paired["verdict"] == "no_significant_difference"
    assert paired["discordant"] == 0
    assert paired["ties"] == 4


def test_adequate_effect_is_paired_significant() -> None:
    from evolver.experiment.stats import MIN_N

    report = ablation.run_stage_exit(
        _tasks(MIN_N),
        record_context=_record_ctx(),
        agent_fn=ablation.make_stub_agent(record_effect=True),
        order_seed=9,
    )
    paired = report["paired"]
    assert paired["verdict"] == "a_better"
    assert paired["p"] <= 0.05


# ---------------------------------------------------------------------------
# Eligibility: the machine-readable preconditions
# ---------------------------------------------------------------------------


def _eligible_evidence(**overrides: Any) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "episodes_used": ["sha256:abc"],
        "control": "placebo",
        "tasks_unique": True,
        "task_digest": "sha256:" + "0" * 64,
        "commit": "deadbee" * 4,
        "order_seed": 7,
        "sampling": {"temperature": "provider-default", "seed": None, "max_tokens": 16384},
        "report_path": "/tmp/out.json",
    }
    evidence.update(overrides)
    return evidence


def test_eligibility_names_every_missing_precondition() -> None:
    eligible, reasons = ablation.check_stage_eligibility(
        _eligible_evidence(episodes_used=[], control="empty", commit="", report_path="")
    )
    assert eligible is False
    assert any("episodes" in r for r in reasons)
    assert any("placebo" in r for r in reasons)
    assert any("commit" in r for r in reasons)
    assert any("output" in r for r in reasons)


def test_eligibility_passes_when_all_preconditions_hold() -> None:
    eligible, reasons = ablation.check_stage_eligibility(_eligible_evidence())
    assert eligible is True
    assert reasons == []


def test_ineligible_report_cannot_be_stage_positive() -> None:
    report = ablation.run_stage_exit(
        _tasks(2),
        record_context=_record_ctx(),
        agent_fn=ablation.make_stub_agent(record_effect=True),
        order_seed=0,
    )
    report["stage_exit_evidence"] = _eligible_evidence(episodes_used=[])
    verdict = ablation.stage_exit_verdict(report)
    assert verdict["eligible"] is False
    assert verdict["stage"] == "ineligible"
    assert verdict["stage_stop"] is False


def test_tokens_only_signal_is_never_stage_positive() -> None:
    report = ablation.run_stage_exit(
        _tasks(2),
        record_context=_record_ctx(),
        agent_fn=ablation.make_stub_agent(record_effect=True),
        order_seed=0,
    )
    # Force the tokens-only shape: equal success, fewer tokens with records.
    report["comparison"] = {
        "success_rate_delta": 0.0,
        "success_rate_pct": "+0.0%",
        "token_delta_pct": "-10.0%",
        "evolved_better": True,
    }
    report["stage_exit_evidence"] = _eligible_evidence()
    verdict = ablation.stage_exit_verdict(report)
    assert verdict["signal_basis"] == "tokens_only"
    assert verdict["stage"] == "inconclusive"


def test_adequate_success_rate_signal_with_paired_proof_is_stage_positive() -> None:
    from evolver.experiment.stats import MIN_N

    report = ablation.run_stage_exit(
        _tasks(MIN_N),
        record_context=_record_ctx(),
        agent_fn=ablation.make_stub_agent(record_effect=True),
        order_seed=11,
    )
    report["stage_exit_evidence"] = _eligible_evidence()
    verdict = ablation.stage_exit_verdict(report)
    assert verdict["sample_adequate"] is True
    assert verdict["signal_basis"] == "success_rate"
    assert verdict["stage"] == "positive"
    assert verdict["stage_stop"] is False


def test_adequate_no_signal_stops_the_stage() -> None:
    from evolver.experiment.stats import MIN_N

    report = ablation.run_stage_exit(
        _tasks(MIN_N),
        record_context=_record_ctx(),
        agent_fn=ablation.make_stub_agent(record_effect=False),
        order_seed=13,
    )
    report["stage_exit_evidence"] = _eligible_evidence()
    verdict = ablation.stage_exit_verdict(report)
    assert verdict["stage"] == "negative-stop"
    assert verdict["stage_stop"] is True


# ---------------------------------------------------------------------------
# run_llm_stage_exit: sampling frozen, served model per call (no network)
# ---------------------------------------------------------------------------


class _StageFakeClient:
    """Fake DeepSeekClient that accepts sampling params and splits usage."""

    built: list[_StageFakeClient] = []

    def __init__(self, **kwargs: Any) -> None:
        self.model = kwargs.get("model")
        self.max_tokens = kwargs.get("max_tokens", 4096)
        self.timeout_s = kwargs.get("timeout_s", 120)
        self.temperature = kwargs.get("temperature")
        self.seed = kwargs.get("seed")
        self.api_key = "test-key"
        self.last_server_model = ""
        _StageFakeClient.built.append(self)

    def complete_prompt(
        self, prompt: str, *, context: str = "", max_tokens: int | None = None
    ) -> tuple[str, dict[str, int]]:
        self.last_server_model = "deepseek-flash"
        if "boom" in prompt:
            from evolver.experiment.llm import LLMError

            raise LLMError("LLM HTTP 429: rate limited")
        if ablation.RECORD_MARKER in context:
            return (
                "solved def f",
                {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
            )
        return ("unsolved", {"prompt_tokens": 40, "completion_tokens": 20, "total_tokens": 60})


def _patch_stage_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from evolver.experiment import ablation_llm

    _StageFakeClient.built.clear()
    monkeypatch.setattr(ablation_llm, "DeepSeekClient", _StageFakeClient)


def test_sampling_params_forwarded_and_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    from evolver.experiment import ablation_llm

    _patch_stage_client(monkeypatch)
    report = ablation_llm.run_llm_stage_exit(
        _tasks(2), _record_ctx(), temperature=0.0, seed=123, order_seed=5
    )
    assert _StageFakeClient.built[-1].temperature == 0.0
    assert _StageFakeClient.built[-1].seed == 123
    assert report["sampling"] == {
        "temperature": 0.0,
        "seed": 123,
        "max_tokens": ablation_llm.DEFAULT_ABLATION_MAX_TOKENS,
        "timeout_s": 120,
    }


def test_unset_sampling_records_provider_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from evolver.experiment import ablation_llm

    _patch_stage_client(monkeypatch)
    report = ablation_llm.run_llm_stage_exit(_tasks(2), _record_ctx())
    assert report["sampling"]["temperature"] == "provider-default"
    assert report["sampling"]["seed"] is None


def test_per_call_server_model_and_prompt_balance(monkeypatch: pytest.MonkeyPatch) -> None:
    from evolver.experiment import ablation_llm

    _patch_stage_client(monkeypatch)
    report = ablation_llm.run_llm_stage_exit(
        _tasks(2),
        _record_ctx(),
        control_context=ablation.make_placebo_context(_record_ctx()),
        order_seed=5,
    )
    assert all(c["server_model"] == "deepseek-flash" for c in report["calls"])
    balance = report["prompt_token_balance"]
    assert balance["status"] == "measured"
    assert balance["with_avg_prompt_tokens"] == 50.0
    assert balance["without_avg_prompt_tokens"] == 40.0
    assert balance["delta_pct"] == pytest.approx(0.25)


def test_stage_llm_error_is_a_classified_call_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from evolver.experiment import ablation_llm

    _patch_stage_client(monkeypatch)
    tasks = [
        {"id": "t-ok", "prompt": "write f", "expected": "def f"},
        {"id": "t-bad", "prompt": "boom write f", "expected": "def f"},
    ]
    report = ablation_llm.run_llm_stage_exit(tasks, _record_ctx(), order_seed=0)
    bad_calls = [c for c in report["calls"] if c["task_id"] == "t-bad"]
    assert len(bad_calls) == 2
    assert all(c["error_class"] == "http_429" for c in bad_calls)
    assert all(c["server_model"] == "" for c in bad_calls)
    assert report["with_records"]["total"] == 2


# ---------------------------------------------------------------------------
# DeepSeekClient: sampling params ride along only when frozen
# ---------------------------------------------------------------------------


def _fake_urlopen_body(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], dict[str, Any]]:
    import json as json_lib
    import urllib.request

    seen: dict[str, Any] = {}
    payload = {
        "model": "deepseek-flash",
        "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }

    class _Resp:
        def __init__(self) -> None:
            self._body = json_lib.dumps(payload).encode("utf-8")

        def read(self) -> bytes:
            return self._body

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *args: Any) -> bool:
            return False

    def fake(req: Any, **kwargs: Any) -> _Resp:
        data = req.data or b"{}"
        seen["body"] = json_lib.loads(data.decode("utf-8"))
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    return seen, payload


def test_sampling_absent_from_body_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from evolver.experiment.llm import DeepSeekClient

    for key in ("DEEPSEEK_API_KEY", "DEEPSEEK_APIKEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"):
        monkeypatch.delenv(key, raising=False)
    seen, _ = _fake_urlopen_body(monkeypatch)
    DeepSeekClient(api_key="k").complete([{"role": "user", "content": "hi"}])
    assert "temperature" not in seen["body"]
    assert "seed" not in seen["body"]


def test_frozen_sampling_reaches_the_body(monkeypatch: pytest.MonkeyPatch) -> None:
    from evolver.experiment.llm import DeepSeekClient

    for key in ("DEEPSEEK_API_KEY", "DEEPSEEK_APIKEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"):
        monkeypatch.delenv(key, raising=False)
    seen, _ = _fake_urlopen_body(monkeypatch)
    DeepSeekClient(api_key="k", temperature=0.0, seed=7).complete(
        [{"role": "user", "content": "hi"}]
    )
    assert seen["body"]["temperature"] == 0.0
    assert seen["body"]["seed"] == 7


# ---------------------------------------------------------------------------
# CLI gates: ineligible setups exit 2 instead of reporting
# ---------------------------------------------------------------------------


def _write_tasks(tmp_path: Path, tasks: list[dict[str, Any]]) -> Path:
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(json.dumps(tasks), encoding="utf-8")
    return tasks_file


def _record_one_episode() -> str:
    from evolver.gep import episode_record

    scene = {
        "event": {
            "type": "EvolutionEvent",
            "id": "evt_stage_1",
            "run_id": "run_stage_1",
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
    body = episode_record.build_episode(scene)
    return str(episode_record.record_episode(body)["id"])


def _fake_stage_run(tasks: list[dict[str, Any]], context: str, **kwargs: Any) -> dict[str, Any]:
    report = ablation.run_stage_exit(
        tasks,
        record_context=context,
        agent_fn=ablation.make_stub_agent(record_effect=True),
        control_context=kwargs.get("control_context", ""),
        order_seed=kwargs.get("order_seed", 0),
    )
    report["model_requested"] = kwargs.get("model", "deepseek-flash")
    report["server_models"] = ["deepseek-flash"]
    report["sampling"] = {
        "temperature": "provider-default",
        "seed": None,
        "max_tokens": 16384,
        "timeout_s": 120,
    }
    report["verdict"] = ablation.ablation_verdict(report)
    report["errors"] = []
    return report


def test_cli_stage_exit_needs_episodes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from evolver.experiment import cli as exp_cli

    tasks_file = _write_tasks(tmp_path, _tasks(2))
    rc = exp_cli.main(
        [
            "--tasks",
            str(tasks_file),
            "--ablation",
            "--stage-exit",
            "--placebo",
            "--output",
            str(tmp_path / "out.json"),
        ]
    )
    assert rc == 2
    assert "requires --from-episodes" in capsys.readouterr().err


def test_cli_stage_exit_needs_placebo(
    tmp_path: Path, temp_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from evolver.experiment import cli as exp_cli

    _record_one_episode()
    tasks_file = _write_tasks(tmp_path, _tasks(2))
    rc = exp_cli.main(
        [
            "--tasks",
            str(tasks_file),
            "--ablation",
            "--stage-exit",
            "--from-episodes",
            "--output",
            str(tmp_path / "out.json"),
        ]
    )
    assert rc == 2
    assert "requires --placebo" in capsys.readouterr().err


def test_cli_stage_exit_needs_output(
    tmp_path: Path, temp_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from evolver.experiment import cli as exp_cli

    _record_one_episode()
    tasks_file = _write_tasks(tmp_path, _tasks(2))
    rc = exp_cli.main(
        ["--tasks", str(tasks_file), "--ablation", "--stage-exit", "--from-episodes", "--placebo"]
    )
    assert rc == 2
    assert "requires --output" in capsys.readouterr().err


def test_cli_stage_exit_rejects_empty_store(
    tmp_path: Path, temp_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from evolver.experiment import cli as exp_cli

    tasks_file = _write_tasks(tmp_path, _tasks(2))
    rc = exp_cli.main(
        [
            "--tasks",
            str(tasks_file),
            "--ablation",
            "--stage-exit",
            "--from-episodes",
            "--placebo",
            "--output",
            str(tmp_path / "out.json"),
        ]
    )
    assert rc == 2
    assert "no episodes" in capsys.readouterr().err


def test_cli_stage_exit_rejects_file_context(
    tmp_path: Path, temp_workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from evolver.experiment import cli as exp_cli

    _record_one_episode()
    tasks_file = _write_tasks(tmp_path, _tasks(2))
    ctx_file = tmp_path / "ctx.txt"
    ctx_file.write_text("HAND-CARRIED", encoding="utf-8")
    rc = exp_cli.main(
        [
            "--tasks",
            str(tasks_file),
            "--ablation",
            "--stage-exit",
            "--from-episodes",
            "--placebo",
            "--output",
            str(tmp_path / "out.json"),
            "--record-context-file",
            str(ctx_file),
        ]
    )
    assert rc == 2
    assert "episode store" in capsys.readouterr().err


def test_cli_stage_exit_rejects_duplicate_tasks(
    tmp_path: Path,
    temp_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from evolver.experiment import ablation_llm
    from evolver.experiment import cli as exp_cli

    _record_one_episode()
    dupes = [*_tasks(1), {"id": "t0", "prompt": "again", "expected": "solved"}]
    tasks_file = _write_tasks(tmp_path, dupes)
    monkeypatch.setattr(ablation_llm, "run_llm_stage_exit", _fake_stage_run)
    rc = exp_cli.main(
        [
            "--tasks",
            str(tasks_file),
            "--ablation",
            "--stage-exit",
            "--from-episodes",
            "--placebo",
            "--output",
            str(tmp_path / "out.json"),
        ]
    )
    assert rc == 2
    assert "duplicate" in capsys.readouterr().err


def test_cli_stage_exit_happy_path_writes_eligible_report(
    tmp_path: Path,
    temp_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from evolver.experiment import ablation_llm
    from evolver.experiment import cli as exp_cli

    ep_id = _record_one_episode()
    tasks_file = _write_tasks(tmp_path, _tasks(2))
    out_file = tmp_path / "out.json"
    monkeypatch.setattr(ablation_llm, "run_llm_stage_exit", _fake_stage_run)
    monkeypatch.setattr(exp_cli, "_detect_commit", lambda: "deadbee" * 7)
    rc = exp_cli.main(
        [
            "--tasks",
            str(tasks_file),
            "--ablation",
            "--stage-exit",
            "--from-episodes",
            "--placebo",
            "--output",
            str(out_file),
            "--order-seed",
            "7",
        ]
    )
    assert rc == 0
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved["episodes_used"] == [ep_id]
    assert saved["order_seed"] == 7
    assert len(saved["calls"]) == 4
    assert saved["task_digest"].startswith("sha256:")
    assert saved["stage_exit_evidence"]["commit"] == "deadbee" * 7
    assert saved["stage_exit"]["eligible"] is True
    # n=2 < MIN_N: eligible but under-powered — never a stage conclusion.
    assert saved["stage_exit"]["stage"] == "inconclusive"
    assert saved["stage_exit"]["stage_stop"] is False
