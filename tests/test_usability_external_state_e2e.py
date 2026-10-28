"""Unit and E2E tests for the Usability & Externalized Runtime Data Plan (U-1..U-14)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evolver.bench import frozen_gate
from evolver.cli import main as cli_main
from evolver.gep.eval_worktree import isolated_eval_cwd
from evolver.gep.hypothesis import (
    hypothesis_path,
    load_hypothesis,
    record_hypothesis,
)
from evolver.gep.paths import (
    compute_workspace_id,
    detect_legacy_in_repo_state,
    discover_git_candidates,
    ensure_workspace_meta,
    get_evolution_dir,
    get_gep_assets_dir,
    get_logs_dir,
    get_memory_dir,
    get_repo_root,
    get_workspace_state_dir,
    resolve_legacy_read_path,
)
from evolver.gep.solidify import (
    _classify_env_blockers,
    _read_solidify_state,
    _validate_related_commands,
    solidify,
    write_state_for_solidify,
)
from evolver.swarm import (
    swarm_boot,
    swarm_distill,
    swarm_feedback,
    swarm_host_round,
    swarm_solidify,
    swarm_status,
    swarm_tick,
)
from tests.conftest import SYNTHETIC_VAL_PACK, synth_hypothesis


def _init_git_repo(repo: Path) -> Path:
    """Create a minimal git repo with one initial commit."""
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "src").mkdir(exist_ok=True)
    (repo / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "initial commit"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo


def _arm_synthetic_pack() -> None:
    """Arm the frozen val pack in the current environment so solidify can publish."""
    pack_path = frozen_gate.frozen_pack_path()
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    pack_path.write_text(json.dumps(SYNTHETIC_VAL_PACK, indent=2) + "\n", encoding="utf-8")

    def _fill(text: str) -> None:
        for index in (1, 2):
            root = frozen_gate.sandbox_root(pack_path, replicate=index)
            for task in SYNTHETIC_VAL_PACK["tasks"]:
                slot = root / str(task["id"])
                slot.mkdir(parents=True, exist_ok=True)
                (slot / "out.txt").write_text(text, encoding="utf-8")

    _fill("wrong")
    parent = frozen_gate.establish_parent_baseline()
    assert parent.get("ok") is True, parent
    _fill("x")


# ---------------------------------------------------------------------------
# U-1 & U-3: Workspace ID, Externalized State Root & Repo Resolution
# ---------------------------------------------------------------------------


def test_u1_u3_externalized_workspace_paths_zero_repo_footprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    state_root = tmp_path / "evolver_home"
    monkeypatch.setenv("EVOLVER_STATE_ROOT", str(state_root))
    monkeypatch.setenv("WORKSPACE_DIR", str(repo))
    for k in ("MEMORY_DIR", "EVOLUTION_DIR", "GEP_ASSETS_DIR", "EVOLVER_LOGS_DIR"):
        monkeypatch.delenv(k, raising=False)

    ws_id = compute_workspace_id(repo)
    assert len(ws_id) == 16
    assert not (repo / ".evolver-workspace-id").exists()

    ws_dir = get_workspace_state_dir(repo)
    assert ws_dir == state_root / "workspaces" / ws_id
    assert get_evolution_dir() == ws_dir / "evolution"
    assert get_gep_assets_dir() == ws_dir / "gep"
    assert get_memory_dir() == ws_dir
    assert get_logs_dir() == ws_dir / "logs"
    assert hypothesis_path() == ws_dir / "evolution" / "hypothesis.json"

    meta = ensure_workspace_meta(repo)
    assert (ws_dir / "meta.json").is_file()
    assert meta["workspace_id"] == ws_id
    assert Path(meta["repo_root"]).resolve() == repo.resolve()


def test_u1_repo_root_resolution_from_config_and_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_git_repo(tmp_path / "projects" / "my_repo")
    scratch = tmp_path / "scratch_cwd"
    scratch.mkdir(parents=True)
    state_root = tmp_path / "evolver_home"
    state_root.mkdir(parents=True)
    monkeypatch.setenv("EVOLVER_STATE_ROOT", str(state_root))
    for k in ("EVOLVER_REPO_ROOT", "EVOLVER_PROJECT_DIR", "WORKSPACE_DIR", "OPENCLAW_WORKSPACE"):
        monkeypatch.delenv(k, raising=False)

    # 1. Resolve from child subdir inside repo
    subdir = repo / "src" / "nested"
    subdir.mkdir(parents=True)
    assert get_repo_root(subdir) == repo.resolve()

    # 2. Resolve from ~/.evolver/config.json when cwd is an unrelated scratch dir
    (state_root / "config.json").write_text(
        json.dumps({"default_repo_root": str(repo)}), encoding="utf-8"
    )
    assert get_repo_root(scratch) == repo.resolve()


def test_u3_phase1_legacy_read_fallback_and_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _init_git_repo(tmp_path / "legacy_repo")
    state_root = tmp_path / "evolver_home"
    monkeypatch.setenv("EVOLVER_STATE_ROOT", str(state_root))
    monkeypatch.setenv("WORKSPACE_DIR", str(repo))
    monkeypatch.delenv("EVOLVER_QUIET_LEGACY_WARNING", raising=False)

    legacy_evo = repo / "memory" / "evolution"
    legacy_evo.mkdir(parents=True)
    legacy_state_file = legacy_evo / "evolution_solidify_state.json"
    legacy_state_file.write_text(
        json.dumps({"last_run": {"run_id": "legacy_run_001"}}), encoding="utf-8"
    )

    legacy_detected = detect_legacy_in_repo_state(repo)
    assert legacy_detected["has_legacy"] is True
    assert legacy_detected["legacy_evolution_dir"] == str(legacy_evo)

    primary = get_evolution_dir() / "evolution_solidify_state.json"
    resolved = resolve_legacy_read_path(primary, [legacy_state_file])
    assert resolved == legacy_state_file

    err = capsys.readouterr().err
    assert "evolver migrate-state" in err


# ---------------------------------------------------------------------------
# U-2: Actionable not_a_git_repo with suggested_actions
# ---------------------------------------------------------------------------


def test_u2_not_a_git_repo_includes_suggested_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outer = tmp_path / "workspace_container"
    outer.mkdir()
    child_repo = _init_git_repo(outer / "evolver_child")

    monkeypatch.chdir(outer)
    for k in ("EVOLVER_REPO_ROOT", "EVOLVER_PROJECT_DIR", "WORKSPACE_DIR", "OPENCLAW_WORKSPACE"):
        monkeypatch.delenv(k, raising=False)

    candidates = discover_git_candidates(outer)
    assert str(child_repo.resolve()) in candidates

    write_state_for_solidify(
        {
            "run_id": "run_u2_test",
            "selected_gene_id": "gene_u2",
            "signals": ["test"],
            "mutation": {
                "type": "Mutation",
                "id": "mut_u2",
                "category": "repair",
                "validation": [],
            },
        }
    )

    res = solidify()
    assert res["ok"] is False
    assert res["error"] == "not_a_git_repo"
    actions = res.get("suggested_actions")
    assert isinstance(actions, dict)
    assert str(outer.resolve()) in actions["init_git_at"]
    assert str(child_repo.resolve()) in actions["set_repo_root_to"]
    assert "not a git repository" in actions["message"]


# ---------------------------------------------------------------------------
# U-4 & U-5: Stash on Rejection + Restore-Stash + Hypothesis Preservation
# ---------------------------------------------------------------------------


def test_u4_u5_rejected_mutation_stashed_restorable_and_hypothesis_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(repo))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / "evomap_home"))
    monkeypatch.setenv("EVOLVER_ANCHOR_ON_SOLIDIFY", "0")

    _arm_synthetic_pack()

    run_id = "run_u4_u5_test"
    write_state_for_solidify(
        {
            "run_id": run_id,
            "selected_gene_id": "gene_u4",
            "signals": ["test_failure"],
            "mutation": {
                "type": "Mutation",
                "id": "mut_u4",
                "category": "repair",
                "validation": [],
            },
        }
    )

    record_hypothesis(synth_hypothesis(run_id=run_id))
    assert hypothesis_path().is_file()

    # Modify tracked file and create untracked file
    (repo / "src" / "app.py").write_text("def add(a, b):\n    return a + b + 0\n", encoding="utf-8")
    (repo / "src" / "helper.py").write_text("HELPER = True\n", encoding="utf-8")

    # 1. Failing related command -> worktree rolled back into stash, hypothesis preserved
    res_fail = solidify(
        validation_scope="related",
        related_commands=[[sys.executable, "-c", "import sys; sys.exit(1)"]],
    )
    assert res_fail["ok"] is False
    assert res_fail["error"] == "validation_failed"
    assert res_fail.get("rejected_stash") is not None
    assert res_fail["rejected_stash"]["ok"] is True

    # Working tree was rolled back cleanly
    assert "return a + b + 0" not in (repo / "src" / "app.py").read_text(encoding="utf-8")
    assert not (repo / "src" / "helper.py").exists()

    # Hypothesis survived the failed solidify!
    preserved_hyp = load_hypothesis()
    assert preserved_hyp is not None
    assert preserved_hyp.get("preserved_from_failed_run") == run_id

    # 2. Restore stash via solidify(restore_stash=True)
    res_restore = solidify(restore_stash=True)
    assert res_restore["ok"] is True
    assert res_restore["run_id"] == run_id
    assert "return a + b + 0" in (repo / "src" / "app.py").read_text(encoding="utf-8")
    assert (repo / "src" / "helper.py").read_text(encoding="utf-8") == "HELPER = True\n"

    # Refine restored patch and run solidify WITHOUT re-declaring hypothesis
    (repo / "src" / "app.py").write_text(
        "def add(a, b):\n    return int(a) + int(b)\n", encoding="utf-8"
    )

    res_pass = solidify(
        validation_scope="related",
        related_commands=[[sys.executable, "-c", "print('related ok')"]],
    )
    assert res_pass["ok"] is True
    # Now that solidify succeeded, hypothesis.json is consumed (deleted)
    assert not hypothesis_path().exists()


# ---------------------------------------------------------------------------
# U-6: Atomic Solidify State Metadata
# ---------------------------------------------------------------------------


def test_u6_write_state_for_solidify_stamps_metadata() -> None:
    write_state_for_solidify({"run_id": "run_u6_meta", "signals": []})
    state = _read_solidify_state()
    assert state is not None
    assert state["run_id"] == "run_u6_meta"
    assert state["last_run"]["run_id"] == "run_u6_meta"
    assert isinstance(state.get("updated_at"), str)
    assert len(state["updated_at"]) >= 10


# ---------------------------------------------------------------------------
# U-7 & U-8: Validation Scope & Env Blocker Classification
# ---------------------------------------------------------------------------


def test_u7_validate_related_commands_enforces_argv_list() -> None:
    ok1, cmd1, err1 = _validate_related_commands("pytest -q")
    assert ok1 is False
    assert cmd1 == []
    assert "non-empty list" in err1

    ok2, cmd2, err2 = _validate_related_commands([["pytest -q tests/test_foo.py"]])
    assert ok2 is False
    assert cmd2 == []
    assert "spaces in binary name" in err2

    ok3, cmd3, err3 = _validate_related_commands([["pytest", "-q", "tests/test_foo.py"]])
    assert ok3 is True
    assert cmd3 == [["pytest", "-q", "tests/test_foo.py"]]
    assert err3 == ""


def test_u8_classify_env_blockers_separates_unrelated_failures() -> None:
    validation_result = {
        "ok": False,
        "results": [
            {
                "command": "pytest -q",
                "ok": False,
                "stdout": "FAILED tests/test_other_module.py::test_unrelated - AssertionError\n",
                "stderr": "",
            },
            {
                "command": "uv run pytest",
                "ok": False,
                "stdout": "",
                "stderr": "error: failed to open file `.lock`: Access is denied (os error 5)",
            },
        ],
    }
    blockers = _classify_env_blockers(validation_result, changed_files=["src/evolver/foo.py"])
    assert len(blockers) == 2
    kinds = {b["kind"] for b in blockers}
    assert "unrelated_test_failure" in kinds
    assert "env_lock" in kinds


# ---------------------------------------------------------------------------
# U-9: Eval Worktree Whitelist Doc Overlay & Missing Untracked Doc Scan
# ---------------------------------------------------------------------------


def test_u9_eval_worktree_overlays_whitelisted_stage_docs(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text("*方案*.md\n缺失文档.md\n", encoding="utf-8")
    (repo / "易用性演进方案.md").write_text("# 阶段方案\n", encoding="utf-8")
    (repo / "TODO_USABILITY.md").write_text("# TODO\n", encoding="utf-8")
    (repo / "缺失文档.md").write_text("# 被 gitignore 且不在白名单中的文档\n", encoding="utf-8")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_doc_check.py").write_text(
        "from pathlib import Path\n"
        'assert Path("易用性演进方案.md").exists()\n'
        'assert Path("缺失文档.md").exists()\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", ".gitignore", "tests/test_doc_check.py"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "add test"],
        cwd=repo,
        check=True,
    )

    with isolated_eval_cwd(repo) as (eval_cwd, meta):
        assert meta["isolated"] is True
        assert (eval_cwd / "易用性演进方案.md").is_file()
        assert (eval_cwd / "TODO_USABILITY.md").is_file()
        assert "易用性演进方案.md" in meta.get("overlaid_whitelist_docs", [])
        assert "缺失文档.md" in meta.get("missing_untracked_docs", [])


# ---------------------------------------------------------------------------
# U-10, U-11, U-12, U-13: State Health, Migrate-State, Host Round & Checklist
# ---------------------------------------------------------------------------


def test_u10_u11_migrate_state_and_swarm_status_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    state_root = tmp_path / "evolver_home"
    monkeypatch.setenv("EVOLVER_STATE_ROOT", str(state_root))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(repo))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))

    # Populate legacy in-repo directories
    (repo / "memory" / "evolution").mkdir(parents=True)
    (repo / "memory" / "evolution" / "evolution_solidify_state.json").write_text(
        json.dumps({"last_run": {"run_id": "run_migrated"}}), encoding="utf-8"
    )
    (repo / ".evolver" / "gep").mkdir(parents=True)
    (repo / ".evolver" / "gep" / "genes.json").write_text("[]", encoding="utf-8")

    # Run CLI migrate-state
    rc = cli_main(["migrate-state", "--project", str(repo), "--json"])
    assert rc == 0

    ws_dir = get_workspace_state_dir(repo)
    assert (ws_dir / "evolution" / "evolution_solidify_state.json").is_file()
    assert (ws_dir / "gep" / "genes.json").is_file()
    assert (ws_dir / "migration_report.json").is_file()

    status = swarm_status()
    assert status["ok"] is True
    assert status["workspace_id"] == compute_workspace_id(repo)
    assert Path(status["repo_root"]).resolve() == repo.resolve()
    health = status["state_health"]
    assert health["evolution"]["aligned"] is True
    assert health["gep"]["aligned"] is True
    assert health["hypothesis"]["aligned"] is True
    assert health["all_aligned"] is True


async def test_u12_u13_swarm_host_round_and_tick_checklist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.chdir(scratch)
    monkeypatch.setenv("A2A_HUB_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / "evomap_home"))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))
    _arm_synthetic_pack()
    monkeypatch.delenv("EVOLVER_REPO_ROOT", raising=False)

    res = await swarm_host_round(project=str(repo), agent_name="test-host")
    assert res["ok"] is True
    assert Path(res["repo_root"]).resolve() == repo.resolve()
    assert res["workspace_id"] == compute_workspace_id(repo)
    assert isinstance(res["checklist"], dict)
    assert len(res["checklist"]["steps"]) == 5
    assert "## Host Execution Checklist" in (res.get("tick") or {}).get("dispatch_prompt", "")


# ---------------------------------------------------------------------------
# Full E2E Loop from Non-Standard Host Directory
# ---------------------------------------------------------------------------


async def test_full_e2e_loop_from_non_git_host_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify: boot(project=repo) -> tick -> edit -> distill -> hypothesis ->
    failed solidify (stash + hypothesis kept) -> restore-stash -> passing solidify -> feedback,
    all while host cwd is an unrelated non-git directory.
    """
    host_cwd = tmp_path / "mcp_host_scratch"
    host_cwd.mkdir()
    repo = _init_git_repo(tmp_path / "nested" / "target_repo")
    state_root = tmp_path / "evolver_state"

    monkeypatch.setenv("EVOLVER_STATE_ROOT", str(state_root))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / "evomap_home"))
    monkeypatch.setenv("EVOLVER_ANCHOR_ON_SOLIDIFY", "0")
    monkeypatch.setenv("A2A_HUB_URL", "http://127.0.0.1:9")
    for k in (
        "MEMORY_DIR",
        "EVOLUTION_DIR",
        "GEP_ASSETS_DIR",
        "EVOLVER_REPO_ROOT",
        "OPENCLAW_WORKSPACE",
        "WORKSPACE_DIR",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(host_cwd)

    # 1. Boot with explicit project path while cwd is host_cwd
    boot_res = swarm_boot(agent_name="e2e-agent", project=str(repo))
    assert boot_res["ok"] is True
    assert Path(boot_res["repo_root"]).resolve() == repo.resolve()

    # Arm synthetic pack now that project is bound to repo's workspace_id
    _arm_synthetic_pack()

    # 2. Tick generates prompt + checklist and records pending run state in external state root
    tick_res = await swarm_tick()
    assert tick_res["ok"] is True
    assert "## Host Execution Checklist" in tick_res["dispatch_prompt"]

    # 3. Distill a gene
    llm_resp = """```json
{
  "type": "Gene",
  "id": "gene_e2e_usability",
  "category": "optimize",
  "signals_match": ["manual_optimize"],
  "preconditions": [],
  "strategy": ["Add multiply helper to app.py"],
  "constraints": {"max_files": 5, "forbidden_paths": []},
  "validation": ["python -c \\"import sys; sys.exit(0)\\""]
}
```"""
    distill_res = swarm_distill(response_text=llm_resp)
    assert distill_res["ok"] is True

    # 4. Edit code in target repo
    (repo / "src" / "app.py").write_text(
        "def add(a, b):\n    return a + b\n\ndef mul(a, b):\n    return a * b\n",
        encoding="utf-8",
    )

    # 5. Record hypothesis
    state_data = _read_solidify_state() or {}
    run_id = str((state_data.get("last_run") or {}).get("run_id") or "")
    record_hypothesis(synth_hypothesis(run_id=run_id))

    # 6. First solidify fails due to failing related command -> stashed & hypothesis preserved
    fail_solidify = swarm_solidify(
        validation_scope="related",
        related_commands=[[sys.executable, "-c", "import sys; sys.exit(1)"]],
    )
    assert fail_solidify["ok"] is False
    assert fail_solidify.get("rejected_stash", {}).get("ok") is True
    assert hypothesis_path().is_file()

    # 7. Restore stash via swarm_solidify(restore_stash=True)
    restore_res = swarm_solidify(restore_stash=True)
    assert restore_res["ok"] is True
    assert "def mul(a, b):" in (repo / "src" / "app.py").read_text(encoding="utf-8")

    # Refine restored code slightly and re-run solidify without re-recording hypothesis
    (repo / "src" / "app.py").write_text(
        "def add(a, b):\n    return a + b\n\ndef mul(a, b):\n    return int(a) * int(b)\n",
        encoding="utf-8",
    )

    # 8. Second solidify succeeds without re-recording hypothesis
    pass_solidify = swarm_solidify(
        validation_scope="related",
        related_commands=[[sys.executable, "-c", "import sys; sys.exit(0)"]],
    )
    assert pass_solidify["ok"] is True
    assert not hypothesis_path().exists()

    # 9. Submit feedback
    fb_res = swarm_feedback(
        primary_score=0.95,
        metrics={"latency_ms": 12.0},
        textual_gradient="Clean externalized state E2E run.",
    )
    assert fb_res["ok"] is True

    # Verify zero runtime state directories were created inside the git repo
    assert not (repo / "memory").exists()
    assert not (repo / ".evolver").exists()
    assert not (repo / "logs").exists()
