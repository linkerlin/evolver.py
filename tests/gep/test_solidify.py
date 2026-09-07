"""Direct tests for evolver.gep.solidify."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from evolver.gep import solidify as solidify_mod
from evolver.gep.feature_flags import set_flag
from evolver.gep.paths import get_gep_assets_dir, get_solidify_state_path
from evolver.gep.solidify import (
    adapt_gene_from_learning,
    build_soft_failure_learning_signals,
    classify_failure_mode,
    solidify,
    write_state_for_solidify,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_git_repo(ws: Path) -> None:
    _git(ws, "init")
    _git(ws, "config", "user.email", "test@test.com")
    _git(ws, "config", "user.name", "Test")
    (ws / "README.md").write_text("init\n", encoding="utf-8")
    _git(ws, "add", "-A")
    _git(ws, "-c", "commit.gpgsign=false", "commit", "-m", "init")


def _last_run(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run_id": "run_test_solidify",
        "selected_gene_id": "gene_test_solidify",
        "signals": ["test", "area:testing"],
        "mutation": {
            "type": "Mutation",
            "id": "mut_test_solidify",
            "category": "repair",
            "validation": [],
        },
    }
    base.update(overrides)
    return base


@pytest.fixture
def git_ws(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(temp_workspace))
    gep = temp_workspace / ".evolver" / "gep"
    gep.mkdir(parents=True, exist_ok=True)
    (gep / "events.jsonl").write_text("", encoding="utf-8")
    evo = temp_workspace / "memory" / "evolution"
    evo.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("GEP_ASSETS_DIR", str(gep))
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))
    _init_git_repo(temp_workspace)
    return temp_workspace


def test_write_state_atomic(git_ws: Path) -> None:
    _ = git_ws
    write_state_for_solidify(_last_run())
    path = get_solidify_state_path()
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["last_run"]["selected_gene_id"] == "gene_test_solidify"


def test_no_pending_run(git_ws: Path) -> None:
    _ = git_ws
    result = solidify()
    assert result["ok"] is False
    assert result["error"] == "no_pending_run"


def test_not_a_git_repo(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(temp_workspace))
    evo = temp_workspace / "memory" / "evolution"
    evo.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))
    gep = temp_workspace / ".evolver" / "gep"
    gep.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("GEP_ASSETS_DIR", str(gep))
    write_state_for_solidify(_last_run())
    result = solidify()
    assert result["ok"] is False
    assert result["error"] == "not_a_git_repo"


def test_success_skip_validation(git_ws: Path) -> None:
    _ = git_ws
    write_state_for_solidify(_last_run())
    result = solidify(skip_validation=True)
    assert result["ok"] is True
    assert result["event_id"].startswith("evt_")
    assert "files" in result["blast_radius"]


def test_success_empty_validation(git_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = git_ws
    # Legacy path (cascade off): mutation.validation is the validation source.
    set_flag("enable_fitness_cascade", False, persist=False)
    write_state_for_solidify(_last_run(mutation={"id": "m1", "validation": []}))
    assert solidify()["ok"] is True


def test_writes_event_jsonl(git_ws: Path) -> None:
    _ = git_ws
    result = solidify(skip_validation=True) if False else None
    write_state_for_solidify(_last_run())
    result = solidify(skip_validation=True)
    lines = [
        ln
        for ln in (get_gep_assets_dir() / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    evt = json.loads(lines[-1])
    assert evt["type"] == "EvolutionEvent"
    assert evt["id"] == result["event_id"]
    assert evt["outcome"]["status"] == "success"


def test_updates_last_solidify(git_ws: Path) -> None:
    _ = git_ws
    write_state_for_solidify(_last_run())
    solidify(skip_validation=True)
    state = json.loads(get_solidify_state_path().read_text(encoding="utf-8"))
    assert state["last_solidify"]["outcome"] == "success"


def test_mutation_override(git_ws: Path) -> None:
    _ = git_ws
    write_state_for_solidify(_last_run())
    solidify(mutation_override={"id": "mut_override", "validation": []}, skip_validation=True)
    evt = json.loads(
        (get_gep_assets_dir() / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1]
    )
    assert evt["mutation"]["id"] == "mut_override"


def test_blast_counts_dirty(git_ws: Path) -> None:
    (git_ws / "dirty.txt").write_text("hello\nworld\n", encoding="utf-8")
    write_state_for_solidify(_last_run())
    result = solidify(skip_validation=True)
    assert result["blast_radius"]["files"] >= 1


def test_run_validations_success(git_ws: Path) -> None:
    res = solidify_mod._run_validations([[sys.executable, "-c", "print('ok')"]], git_ws)
    assert res["ok"] is True
    assert isinstance(res["results"][0]["command"], str)
    assert "ok" in res["results"][0]["stdout"]


def test_run_validations_failure(git_ws: Path) -> None:
    res = solidify_mod._run_validations([[sys.executable, "-c", "import sys; sys.exit(2)"]], git_ws)
    assert res["ok"] is False


def test_run_validations_timeout(git_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(solidify_mod, "VALIDATION_TIMEOUT_MS", 50)
    res = solidify_mod._run_validations(
        [[sys.executable, "-c", "import time; time.sleep(5)"]], git_ws
    )
    assert res["ok"] is False
    assert res["results"][0]["stderr"]


def test_solidify_validation_failed(git_ws: Path) -> None:
    _ = git_ws
    # Legacy path (cascade off): mutation.validation drives validation.
    set_flag("enable_fitness_cascade", False, persist=False)
    write_state_for_solidify(
        _last_run(
            mutation={
                "id": "mut_fail",
                "validation": [[sys.executable, "-c", "import sys; sys.exit(1)"]],
            }
        )
    )
    result = solidify()
    assert result["ok"] is False
    assert result["error"] == "validation_failed"


def test_solidify_validation_success(git_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = git_ws
    # Legacy path (cascade off): mutation.validation drives validation.
    set_flag("enable_fitness_cascade", False, persist=False)
    write_state_for_solidify(
        _last_run(
            mutation={
                "id": "mut_ok",
                "validation": [[sys.executable, "-c", "print(1)"]],
            }
        )
    )
    result = solidify()
    assert result["ok"] is True
    evt = json.loads(
        (get_gep_assets_dir() / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1]
    )
    assert isinstance(evt.get("execution_trace"), list)


def test_skip_ignores_failing(git_ws: Path) -> None:
    _ = git_ws
    write_state_for_solidify(
        _last_run(
            mutation={
                "id": "mut_skip",
                "validation": [[sys.executable, "-c", "import sys; sys.exit(1)"]],
            }
        )
    )
    assert solidify(skip_validation=True)["ok"] is True


def test_classify_soft_validation() -> None:
    r = classify_failure_mode(
        validation={"ok": False, "results": [{"ok": False}]},
        canary={"ok": True, "skipped": False},
    )
    assert r == {"mode": "soft", "reasonClass": "validation", "retryable": True}


def test_classify_hard_destructive() -> None:
    r = classify_failure_mode(
        constraint_violations=["CRITICAL_FILE_DELETED: MEMORY.md"],
        validation={"ok": True},
    )
    assert r["mode"] == "hard"
    assert r["reasonClass"] == "constraint_destructive"
    assert r["retryable"] is False


def test_classify_hard_protocol() -> None:
    r = classify_failure_mode(protocol_violations=["schema"], validation={"ok": True})
    assert r["mode"] == "hard"
    assert r["reasonClass"] == "protocol"


def test_classify_none() -> None:
    r = classify_failure_mode(validation={"ok": True}, canary={"ok": True, "skipped": False})
    assert r["mode"] == "none"


def test_classify_soft_canary() -> None:
    r = classify_failure_mode(validation={"ok": True}, canary={"ok": False, "skipped": False})
    assert r["mode"] == "soft"
    assert r["reasonClass"] == "canary"


def test_adapt_success_broadens() -> None:
    gene: dict[str, Any] = {"id": "g", "signals_match": ["error"]}
    adapt_gene_from_learning(
        gene=gene,
        outcome_status="success",
        learning_signals=["problem:performance", "action:optimize", "area:orchestration"],
        failure_mode={"mode": "none"},
    )
    assert "problem:performance" in gene["signals_match"]
    assert "area:orchestration" in gene["signals_match"]
    assert "action:optimize" not in gene["signals_match"]
    assert gene["learning_history"][0]["outcome"] == "success"


def test_adapt_failure_anti_patterns() -> None:
    gene: dict[str, Any] = {"id": "g", "signals_match": ["protocol"]}
    adapt_gene_from_learning(
        gene=gene,
        outcome_status="failed",
        learning_signals=["problem:protocol"],
        failure_mode={"mode": "soft", "reasonClass": "validation"},
    )
    assert gene["signals_match"] == ["protocol"]
    assert gene["anti_patterns"][0]["mode"] == "soft"


def test_soft_failure_signals_perf() -> None:
    tags = build_soft_failure_learning_signals(
        signals=["perf_bottleneck"],
        failure_reason="latency remained high",
        validation_results=[{"ok": False, "cmd": "npm test", "stderr": "latency"}],
    )
    assert "problem:performance" in tags
    assert "risk:validation" in tags


def test_soft_failure_timeout() -> None:
    tags = build_soft_failure_learning_signals(
        failure_reason="timed out",
        validation_results=[{"ok": False, "cmd": "pytest", "stderr": "timeout"}],
    )
    assert "problem:timeout" in tags


def test_soft_failure_protocol() -> None:
    tags = build_soft_failure_learning_signals(
        failure_reason="invalid json schema",
        violations=["schema"],
    )
    assert "problem:protocol" in tags


def test_soft_failure_dedupe() -> None:
    tags = build_soft_failure_learning_signals(
        signals=["latency"],
        failure_reason="performance latency",
        validation_results=[{"ok": False, "cmd": "x", "stderr": "slow"}],
    )
    assert tags.count("problem:performance") == 1


def test_blast_clean(git_ws: Path) -> None:
    _ = git_ws
    br = solidify_mod._compute_blast_radius()
    assert br["files"] == 0


def test_blast_untracked(git_ws: Path) -> None:
    (git_ws / "a.py").write_text("x\ny\n", encoding="utf-8")
    br = solidify_mod._compute_blast_radius()
    assert br["files"] >= 1
    assert br["lines"] >= 2


def test_preserves_signals(git_ws: Path) -> None:
    _ = git_ws
    write_state_for_solidify(_last_run(signals=["sig_a", "sig_b"]))
    solidify(skip_validation=True)
    evt = json.loads(
        (get_gep_assets_dir() / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1]
    )
    assert evt["signals"] == ["sig_a", "sig_b"]


def test_run_id_from_mutation(git_ws: Path) -> None:
    _ = git_ws
    lr = _last_run()
    del lr["run_id"]
    lr["mutation"] = {"id": "mut_only_id", "validation": []}
    write_state_for_solidify(lr)
    solidify(skip_validation=True)
    evt = json.loads(
        (get_gep_assets_dir() / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1]
    )
    assert evt["run_id"] == "mut_only_id"


def test_write_state_overwrites(git_ws: Path) -> None:
    _ = git_ws
    write_state_for_solidify(_last_run(run_id="first"))
    write_state_for_solidify(_last_run(run_id="second"))
    state = json.loads(get_solidify_state_path().read_text(encoding="utf-8"))
    assert state["last_run"]["run_id"] == "second"


def test_multi_validation_ok(git_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = git_ws
    # Legacy path (cascade off): mutation.validation drives validation.
    set_flag("enable_fitness_cascade", False, persist=False)
    write_state_for_solidify(
        _last_run(
            mutation={
                "id": "mut_multi",
                "validation": [
                    [sys.executable, "-c", "print('a')"],
                    [sys.executable, "-c", "print('b')"],
                ],
            }
        )
    )
    assert solidify()["ok"] is True


def test_multi_validation_second_fails(git_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = git_ws
    # Legacy path (cascade off): both commands must run (no short-circuit).
    set_flag("enable_fitness_cascade", False, persist=False)
    write_state_for_solidify(
        _last_run(
            mutation={
                "id": "mut_multi_fail",
                "validation": [
                    [sys.executable, "-c", "print('a')"],
                    [sys.executable, "-c", "import sys; sys.exit(1)"],
                ],
            }
        )
    )
    result = solidify()
    assert result["ok"] is False
    assert len(result["details"]["results"]) == 2


def test_duplicate_solidify_refused(git_ws: Path) -> None:
    # Round-12: a second solidify on an already-landed run used to burn a
    # full cascade and append a phantom success event, polluting the
    # acceptance gate's soak sample.
    _ = git_ws
    write_state_for_solidify(_last_run())
    first = solidify(skip_validation=True)
    assert first["ok"] is True

    second = solidify(skip_validation=True)
    assert second["ok"] is False
    assert second["error"] == "already_solidified"
    assert second["next_action"] == "swarm_tick"


def test_new_run_after_solidify_not_blocked(git_ws: Path) -> None:
    _ = git_ws
    write_state_for_solidify(_last_run())
    assert solidify(skip_validation=True)["ok"] is True

    # A fresh dispatch writes a new last_run — must solidify fine.
    state = json.loads(get_solidify_state_path().read_text(encoding="utf-8"))
    state["last_run"] = dict(state["last_run"], run_id="run_newer")
    get_solidify_state_path().write_text(json.dumps(state), encoding="utf-8")
    result = solidify(skip_validation=True)
    assert result.get("error") != "already_solidified"


def test_validation_env_prepends_tool_dirs(monkeypatch: pytest.MonkeyPatch) -> None:
    # Round-13: GUI-spawned MCP hosts propagate the launchd minimal PATH;
    # validation must measure the repo, not the host app's environment.
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    env = solidify_mod._validation_env()
    parts = env["PATH"].split(os.pathsep)
    assert parts[0] == str(Path(sys.executable).parent)
    assert "/usr/bin" in parts  # never drops inherited entries
    assert "/opt/homebrew/bin" in parts or "/usr/local/bin" in parts


def test_run_validations_augments_crippled_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    result = solidify_mod._run_validations(
        [[sys.executable, "-c", "import os; print(os.environ['PATH'])"]],
        tmp_path,
    )
    assert result["ok"] is True
    assert str(Path(sys.executable).parent) in result["results"][0]["stdout"]


def test_bounded_output_keeps_head_and_tail() -> None:
    # Failure summaries sit at the very END of pytest output (as in a real run).
    long_text = "A" * 5000 + "B" * 5000 + "\nFAILED tests/x.py"
    bounded = solidify_mod._bounded_output(long_text)
    assert "FAILED tests/x.py" in bounded  # tail summary survives
    assert bounded.startswith("A" * 10)
    assert solidify_mod._bounded_output("short") == "short"
    assert solidify_mod._bounded_output(None) == ""


def test_legacy_rollback_deletes_relative_to_workspace_not_cwd(
    git_ws: Path, monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """DEBUG #20: the legacy validation-failure path listed untracked files in
    the isolated workspace but deleted them from Path.cwd(). Under a cascade
    that cwd is the real repo, so the workspace-relative runtime-state path
    named the engine's OWN state file there and deleted it mid-cascade."""
    proc_cwd = tmp_path_factory.mktemp("proccwd")
    victim_dir = proc_cwd / "memory" / "evolution"
    victim_dir.mkdir(parents=True)
    victim = victim_dir / "evolution_solidify_state.json"
    victim.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(proc_cwd)
    set_flag("enable_fitness_cascade", False, persist=False)
    write_state_for_solidify(
        _last_run(
            mutation={
                "id": "mut_cwd_rollback",
                "validation": [[sys.executable, "-c", "import sys; sys.exit(1)"]],
            }
        )
    )
    result = solidify()
    assert result["ok"] is False
    assert result["error"] == "validation_failed"
    assert victim.exists()  # deletion must be relative to the workspace, not cwd
