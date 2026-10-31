"""Open-box setup/doctor + actionable MCP/CLI error next-steps."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _init_git_repo(path: Path) -> Path:
    import subprocess

    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    (path / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    return path


def test_next_steps_catalog_covers_required_errors() -> None:
    from evolver.ops.open_box import ACTIONABLE_ERRORS, next_steps_for

    for code in ACTIONABLE_ERRORS:
        payload = next_steps_for(code)
        assert payload["next_steps"], code
        assert payload["commands"], code
        blob = json.dumps(payload, ensure_ascii=False).lower()
        assert "please unlock val" not in blob
        assert "please decode val" not in blob
        assert "decrypt" not in blob


def test_no_baseline_steps_forbid_candidate_val_solve() -> None:
    from evolver.ops.open_box import next_steps_for

    payload = next_steps_for("no_baseline", context={"pending_tasks": ["val_a"]})
    text = " ".join(payload["next_steps"]).lower()
    assert "another" in text or "separate" in text
    assert "never" in text or "not" in text
    assert payload["pending_tasks"] == ["val_a"]
    assert "evolver bench baseline" in " ".join(payload["commands"])


def test_diagnose_detects_missing_pack_and_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evolver.ops.open_box import diagnose

    repo = _init_git_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / "evomap_home"))
    monkeypatch.setenv("EVOLVER_STATE_ROOT", str(tmp_path / "state"))

    report = diagnose(project=repo)
    by_id = {c["id"]: c for c in report["checks"]}
    assert by_id["git"]["ok"] is True
    assert by_id["freeze_pack"]["ok"] is False
    assert by_id["freeze_pack"]["error"] == "pack_absent"
    assert by_id["parent_baseline"]["ok"] is False
    assert report["loop_ready"] is False
    assert report["soft_continue"] is True
    assert report["ok"] is True  # soft-continue: not a hard roadblock
    assert report["blockers"] == []
    assert any(r.get("error") == "pack_absent" for r in report.get("recommendations") or [])
    assert report["setup_path"]
    assert "soft-continue" in report["setup_path"] or "recommended" in report["setup_path"]


def test_doctor_fix_freezes_pack_but_does_not_invent_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evolver.bench.frozen_gate import load_baseline, load_frozen_pack
    from evolver.ops.open_box import doctor

    repo = _init_git_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / "evomap_home"))
    monkeypatch.setenv("EVOLVER_STATE_ROOT", str(tmp_path / "state"))

    assert load_frozen_pack() is None
    report = doctor(fix=True, project=repo)
    assert load_frozen_pack() is not None
    assert load_baseline() is None
    by_id = {c["id"]: c for c in report["checks"]}
    assert by_id["freeze_pack"]["ok"] is True
    assert by_id["parent_baseline"]["ok"] is False
    assert by_id["parent_baseline"]["error"] == "no_baseline"
    actions = [a.get("action") for a in report.get("actions") or []]
    assert "freeze_charter_pack" in actions
    blob = json.dumps(report, ensure_ascii=False).lower()
    assert "decrypt" not in blob
    assert "please unlock val" not in blob


def test_attach_next_steps_on_hypothesis_and_git_errors() -> None:
    from evolver.ops.open_box import attach_next_steps

    hyp = attach_next_steps({"ok": False, "error": "hypothesis_missing"})
    assert hyp["next_steps"]
    assert any("swarm_hypothesis" in s for s in hyp["next_steps"])

    git = attach_next_steps(
        {
            "ok": False,
            "error": "not_a_git_repo",
            "suggested_actions": {"candidates": ["/x"]},
        }
    )
    assert git["commands"]
    assert git["next_steps"]


def test_cli_setup_and_doctor_help() -> None:
    from evolver.cli import _build_parser

    parser = _build_parser()
    ns = parser.parse_args(["doctor", "--json"])
    assert ns.command == "doctor"
    assert ns.json is True
    ns2 = parser.parse_args(["setup", "--project", "."])
    assert ns2.command == "setup"


def test_swarm_tick_gate_gap_includes_next_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from evolver.swarm import swarm_tick

    repo = _init_git_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / "evomap_home"))
    monkeypatch.setenv("EVOLVER_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("EVOLVER_SWARM_GATE_HANDOFF", raising=False)

    result = asyncio.run(swarm_tick(agent_name="test-host"))
    assert result.get("gate_soft_continue") is True
    assert result.get("severity") == "soft"
    assert result.get("gate_gap") in ("pack_absent", "no_baseline")
    assert result.get("gap") in ("pack_absent", "no_baseline")
    assert result.get("error") not in ("pack_absent", "no_baseline", "unmeasured")
    assert result.get("next_steps")
    assert result.get("commands")
    assert result.get("warnings")
    blob = json.dumps(result, ensure_ascii=False).lower()
    assert "decrypt" not in blob
    assert "please unlock val" not in blob


def test_readme_mentions_setup_doctor_and_val_seal() -> None:
    readme = Path("examples/swarm-quickstart/README.md").read_text(encoding="utf-8")
    lowered = readme.lower()
    assert "evolver setup" in readme or "evolver doctor" in readme
    assert "doctor" in lowered or "setup" in lowered
    assert "open sealed" in lowered or "不得解 val" in readme or "密封" in readme

def test_doctor_soft_continue_ok_when_only_usability_gaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pack/baseline gaps stay recommendations; ok/soft_continue true; loop_ready false."""
    from evolver.ops.open_box import doctor

    repo = _init_git_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / "evomap_home"))
    monkeypatch.setenv("EVOLVER_STATE_ROOT", str(tmp_path / "state"))

    report = doctor(fix=False, project=repo)
    assert report["loop_ready"] is False
    assert report["soft_continue"] is True
    assert report["ok"] is True
    assert report["blockers"] == []
    assert report.get("recommendations")
    soft_recs = report.get("recommendations") or []
    assert all(r.get("severity") == "soft" for r in soft_recs)
    assert all(r.get("gap") in ("pack_absent", "no_baseline", "unmeasured") for r in soft_recs)


def test_cli_doctor_exit_zero_on_soft_continue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """doctor CLI must not exit 2 / print NOT READY solely for pack/baseline gaps."""
    from evolver.cli import _cmd_doctor

    repo = _init_git_repo(tmp_path / "repo")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(repo))
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / "evomap_home"))
    monkeypatch.setenv("EVOLVER_STATE_ROOT", str(tmp_path / "state"))

    ns = type("NS", (), {"fix": False, "project": str(repo), "json": False})()
    code = _cmd_doctor(ns)
    out = capsys.readouterr().out
    assert code == 0
    assert "NOT READY" not in out
    assert "SOFT-CONTINUE" in out or "soft-continue" in out.lower()
