"""Tests for evolver.cli entry points."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from evolver.cli import main


@pytest.fixture
def isolated_evolver_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point all evolver state into tmp_path so tests do not touch ~/.evomap."""
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("EVOLVER_USER_LOCK", str(tmp_path / "user.lock"))
    yield tmp_path


def _declare_hypothesis() -> None:
    """配对会话 §5.3 — a Candidate enters the gate carrying exactly one
    hypothesis, stated in observed before/after form. The CLI has no host to
    speak for the Candidate, so the test plays the host's part."""
    from evolver.gep.hypothesis import record_hypothesis

    record_hypothesis(
        {
            "hypothesis": "the dispatch prompt names no explicit success bar",
            "dimension": "content",
            "mechanism_family": "prompt_specificity",
            "target_hook": "gep.prompt.dispatch",
            "mechanism_check": [
                {"id": "train-1", "before": "no bar stated", "after": "bar stated"}
            ],
        }
    )


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--version"])
    assert code == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("evolver ")


def test_cli_run_emits_prompt(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["run"])
    assert code == 0
    captured = capsys.readouterr()
    assert "GENOME EVOLUTION PROTOCOL" in captured.out


def test_cli_solidify_without_state_fails(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["solidify"])
    assert code == 1
    captured = capsys.readouterr()
    assert "no_pending_run" in captured.err


def test_cli_hitl_list_approve_flow(
    isolated_evolver_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EvoX concept harvest: `evolver hitl list/approve/reject` (v1.100.0)."""
    monkeypatch.setattr("evolver.config.HITL_MODE", "on")
    from evolver.gep.hitl import request_approval

    assert main(["hitl", "list"]) == 0
    assert "No pending HITL approvals." in capsys.readouterr().out

    req = request_approval(subject="cli_test:s1", risk_reason="demo risk")
    assert main(["hitl", "list"]) == 0
    assert req["request_id"] in capsys.readouterr().out

    assert main(["hitl", "approve", "--id", req["request_id"], "--note", "ok"]) == 0
    assert "approved" in capsys.readouterr().out

    # Already decided — second resolution fails cleanly.
    assert main(["hitl", "reject", "--id", req["request_id"]]) == 1
    assert "not_pending" in capsys.readouterr().err


def test_cli_supervise_flow(isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """HOTL supervision via CLI (v1.101.0): status/pause/direct/resume."""
    assert main(["supervise", "status"]) == 0
    assert '"state": "running"' in capsys.readouterr().out

    assert main(["supervise", "pause", "--reason", "hold"]) == 0
    assert '"state": "paused"' in capsys.readouterr().out

    assert main(["supervise", "direct", "优先稳定测试"]) == 0
    assert "directive_id" in capsys.readouterr().out

    from evolver.gep.asset_store import consume_pending_signals

    assert any(s.startswith("supervision:directive:") for s in consume_pending_signals())

    assert main(["supervise", "resume"]) == 0
    assert '"state": "running"' in capsys.readouterr().out


def test_cli_gene_lifecycle_flow(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """RSI P1-5: gene-lifecycle list/evaluate/reinstate via CLI."""
    from evolver.gep.asset_store import append_event_jsonl

    for i in range(3):
        append_event_jsonl(
            {
                "id": f"evt_land_{i}",
                "outcome": {"status": "success"},
                "mutation": {"landed_gene_ids": ["gene_dead"]},
                "signals": ["log_error"],
            }
        )
        append_event_jsonl(
            {"id": f"evt_fail_{i}", "outcome": {"status": "failed"}, "signals": ["log_error"]}
        )
    for i in range(5):
        append_event_jsonl(
            {"id": f"evt_ok_{i}", "outcome": {"status": "success"}, "signals": ["hub_offline"]}
        )
    # Round-58: one extra landing of a DIFFERENT gene — below threshold, so
    # it must surface as an approaching candidate (gene_dead reaches 3
    # observations and leaves the near-miss section for the state machine).
    # A descendant event is required: landings without descendants carry 0
    # observations ("silence is not evidence of work").
    append_event_jsonl(
        {
            "id": "evt_land_alive",
            "outcome": {"status": "success"},
            "mutation": {"landed_gene_ids": ["gene_alive"]},
            "signals": ["perf_bottleneck"],
        }
    )
    append_event_jsonl(
        {"id": "evt_desc_alive", "outcome": {"status": "success"}, "signals": ["other"]}
    )

    assert main(["gene-lifecycle", "list"]) == 0
    first_out = capsys.readouterr().out
    assert "no records" in first_out
    assert "gene_alive" in first_out, "near-miss section must name the gene"
    assert "obs=" in first_out

    # Round-65 follow-up: the JSON surface carries the same approaching data.
    assert main(["gene-lifecycle", "list", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["approaching"]["threshold"] == 3
    approaching_ids = [c["gene_id"] for c in payload["approaching"]["candidates"]]
    assert "gene_alive" in approaching_ids

    assert main(["gene-lifecycle", "evaluate", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["transitions"][0]["gene_id"] == "gene_dead"
    assert payload["transitions"][0]["to_status"] == "under_review"

    assert main(["gene-lifecycle", "list"]) == 0
    listing = capsys.readouterr().out
    assert "gene_dead" in listing
    assert "under_review" in listing

    assert main(["gene-lifecycle", "reinstate", "gene_dead", "--note", "retry"]) == 0
    assert "-> active" in capsys.readouterr().out

    assert main(["gene-lifecycle", "reinstate", "gene_dead"]) == 1
    assert "already_active" in capsys.readouterr().err


def _init_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(root)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )


def test_cli_solidify_after_run_is_refused_while_the_gate_is_unarmed(
    isolated_evolver_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配对会话 §5.2 — an unarmed gate is a reject, never a pass.

    No frozen pack means no Parent, so there is nothing to be strictly
    better than. Arming it is a human setup action (``evolver bench freeze``
    then ``evolver bench baseline``); until that happens, a Candidate that
    cannot be measured is not a Candidate that may publish. This replaces an
    older assertion that solidify simply succeeded: "no instrument installed"
    used to read as "measured fine".
    """
    monkeypatch.setenv("EVOLVER_HOME", str(isolated_evolver_env / ".evolver"))
    _init_git_repo(isolated_evolver_env)

    assert main(["run"]) == 0
    _declare_hypothesis()
    code = main(["solidify"])
    assert code != 0
    captured = capsys.readouterr()
    assert "bench_pack_rejected" in captured.err
    assert "pack_absent" in captured.err


def test_cli_solidify_without_a_hypothesis_is_refused(
    isolated_evolver_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配对会话 §5.3 — no hypothesis, no measurement, no publish. A run that
    never stated what it is testing must not be solidified: it would publish
    a mutation nobody can explain."""
    monkeypatch.setenv("EVOLVER_HOME", str(isolated_evolver_env / ".evolver"))
    _init_git_repo(isolated_evolver_env)

    assert main(["run"]) == 0
    code = main(["solidify"])
    assert code != 0
    captured = capsys.readouterr()
    assert "hypothesis_missing" in captured.err


def test_cli_webui_token_generate_and_revoke(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVOLVER_HOME", str(isolated_evolver_env / ".evolver"))
    code = main(["webui-token", "--generate", "--role", "admin"])
    assert code == 0
    captured = capsys.readouterr()
    assert "Token (admin):" in captured.out
    token = captured.out.split(": ")[1].strip()

    code = main(["webui-token"])
    assert code == 0
    captured = capsys.readouterr()
    assert "1 token(s)" in captured.out

    code = main(["webui-token", "--revoke", token])
    assert code == 0
    captured = capsys.readouterr()
    assert "Revoked." in captured.out


# ---------------------------------------------------------------------------
# 库即尺子 round-93: the library CLI entries (pinned round-99)
# ---------------------------------------------------------------------------


def test_cli_library_establish_parent_writes_the_pointer(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = isolated_evolver_env / "parent.json"
    payload.write_text(json.dumps({"genes": [], "capsules": []}), encoding="utf-8")

    assert main(["library", "establish-parent", f"--from={payload}"]) == 0
    out = capsys.readouterr().out
    assert "parent library : sha256:" in out
    assert "untouched" in out  # active stays empty — publish is Accept-only

    from evolver.gep import library

    assert library.parent_snapshot_id() is not None
    assert library.active_snapshot_id() is None


def test_cli_library_establish_parent_missing_file(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["library", "establish-parent", "--from=nope.json"]) == 2
    assert "file not found" in capsys.readouterr().err


def test_cli_library_establish_parent_rejects_non_dict(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = isolated_evolver_env / "parent.json"
    payload.write_text("[1, 2]", encoding="utf-8")
    assert main(["library", "establish-parent", f"--from={payload}"]) == 2
    assert "JSON object" in capsys.readouterr().err


def test_cli_library_establish_parent_json_output(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = isolated_evolver_env / "parent.json"
    payload.write_text(json.dumps({"genes": []}), encoding="utf-8")
    assert main(["library", "establish-parent", f"--from={payload}", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True and report["snapshot"].startswith("sha256:")


# ---------------------------------------------------------------------------
# 经验即证据 §5.1: the episode record CLI and the cycle-boundary write
# ---------------------------------------------------------------------------


def _episode_scene() -> dict[str, object]:
    return {
        "event": {
            "type": "EvolutionEvent",
            "id": "evt_1_abc",
            "run_id": "run_1",
            "timestamp": "2026-10-02T00:00:00.000Z",
            "gene_id": "gene_a",
            "mutation": {"id": "mut_1", "category": "repair"},
            "diff_snapshot": "--- a.py\n+++ b.py\n-x = 1\n+x = 2\n",
            "outcome": {"status": "success", "score": 1.0},
        },
        "validation_result": {
            "ok": True,
            "results": [{"command": "uv run pytest", "ok": True, "stdout": "1 passed"}],
        },
        "fitness_verdict": None,
        "gate": {"accepted": True, "reason": "improved"},
    }


def test_cli_episode_list_and_show_round_trip(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from evolver.gep import episode_record

    body = episode_record.build_episode(_episode_scene())
    stored = episode_record.record_episode(body)

    assert main(["episode", "list"]) == 0
    assert stored["id"] in capsys.readouterr().out

    assert main(["episode", "show", stored["id"]]) == 0
    assert json.loads(capsys.readouterr().out) == body


def test_cli_episode_show_unknown_id_exits_2(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["episode", "show", "sha256:nope"]) == 2
    assert "not found" in capsys.readouterr().err


def test_the_cycle_boundary_records_the_round_it_settled(isolated_evolver_env: Path) -> None:
    """1a 判据: after one settled round the record is readable by id, and it is
    derived from the immutable scene — never from anything the host reports."""
    from evolver.cli import _record_episode_round
    from evolver.gep import episode_record
    from evolver.gep.evidence import save_evidence

    save_evidence("run_1", "evt_1_abc", _episode_scene())
    result = _record_episode_round({"ok": True, "event_id": "evt_1_abc"})
    assert result["ok"] is True
    body = episode_record.load_episode(result["id"])
    assert body is not None
    assert body["run_id"] == "run_1" and body["event_id"] == "evt_1_abc"
    # a missing scene is reported, never guessed
    missing = _record_episode_round({"ok": True, "event_id": "evt_missing"})
    assert missing["ok"] is False and missing["error"] == "scene_missing"


def test_cli_experiment_ablation_forwards_episode_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """取材桥透传: 顶层 `evolver experiment` 的新参数必须到达 experiment_main."""
    import evolver.experiment.cli as exp_cli

    seen: dict[str, list[str]] = {}

    def fake_main(argv: list[str]) -> int:
        seen["argv"] = list(argv)
        return 0

    monkeypatch.setattr(exp_cli, "main", fake_main)
    assert (
        main(
            [
                "experiment",
                "--tasks",
                "tasks.json",
                "--ablation",
                "--from-episodes",
                "--episode-id",
                "sha256:abc",
                "--episodes-limit",
                "3",
                "--episode-max-chars",
                "500",
                "--placebo",
                "--stage-exit",
                "--order-seed",
                "7",
                "--temperature",
                "0.0",
                "--seed",
                "11",
                "--model",
                "deepseek-flash",
            ]
        )
        == 0
    )
    assert seen["argv"] == [
        "--tasks",
        "tasks.json",
        "--ablation",
        "--record-context",
        "",
        "--from-episodes",
        "--episode-id",
        "sha256:abc",
        "--placebo",
        "--stage-exit",
        "--order-seed",
        "7",
        "--temperature",
        "0.0",
        "--seed",
        "11",
        "--episodes-limit",
        "3",
        "--episode-max-chars",
        "500",
        "--model",
        "deepseek-flash",
        "--success-mode",
        "contains",
        "--max-tokens",
        "16384",
    ]


def test_cli_experiment_baseline_passes_no_ablation_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非消融路径不受取材桥参数污染。"""
    import evolver.experiment.cli as exp_cli

    seen: dict[str, list[str]] = {}

    def fake_main(argv: list[str]) -> int:
        seen["argv"] = list(argv)
        return 0

    monkeypatch.setattr(exp_cli, "main", fake_main)
    assert main(["experiment", "--tasks", "t.json", "--genes", "g.json"]) == 0
    assert seen["argv"] == ["--tasks", "t.json", "--genes", "g.json"]


def test_load_episode_index_unreadable_store_yields_empty(
    isolated_evolver_env: Path,
) -> None:
    """_load_episode_index 是尽力而为: 轮账损坏给空表, 不炸 meta-report."""
    from evolver.cli import _load_episode_index
    from evolver.gep import episode_record

    path = episode_record.index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{corrupt", encoding="utf-8")
    assert _load_episode_index() == []
