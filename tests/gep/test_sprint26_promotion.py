"""S26 promotion tests (演进方案_wikiskill对照版.md §S26.2/§S26.3).

Quantitative fitness becomes the DEFAULT path: fitness cascade on, failure
events on, acceptance gate on in shadow mode, and honest outcome scores
(measured 1.0 vs unvalidated None).

Module mapping note (AGENTS.md 测试 convention): this file covers the
*promotion contract* across `evolver.gep.solidify` + `evolver.gep.
feature_flags` + `evolver.config` — a cross-module contract, so it is named
by sprint rather than by module.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from evolver.config import ACCEPTANCE_SHADOW
from evolver.gep import solidify as solidify_mod
from evolver.gep.feature_flags import DEFAULT_FLAGS, is_enabled, set_flag
from evolver.gep.paths import get_gep_assets_dir
from evolver.gep.solidify import solidify, write_state_for_solidify


def _git(cwd: Path, *args: str) -> None:
    import subprocess

    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


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
    _git(temp_workspace, "init")
    _git(temp_workspace, "config", "user.email", "test@test.com")
    _git(temp_workspace, "config", "user.name", "Test")
    (temp_workspace / "README.md").write_text("init\n", encoding="utf-8")
    _git(temp_workspace, "add", "-A")
    _git(temp_workspace, "-c", "commit.gpgsign=false", "commit", "-m", "init")
    return temp_workspace


def _last_run(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run_id": "run_s26",
        "selected_gene_id": "gene_s26",
        "signals": ["test"],
        "mutation": {"type": "Mutation", "id": "mut_s26", "category": "repair", "validation": []},
    }
    base.update(overrides)
    return base


def _last_event() -> dict[str, Any]:
    lines = [
        ln
        for ln in (get_gep_assets_dir() / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    return json.loads(lines[-1])


def test_promoted_flags_default_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Isolate the disk layer: the repo's own evolver/.config/disk_flags.json
    # must not leak into "what does a fresh install default to".
    from evolver.gep import feature_flags as ff

    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    for name in (
        "enable_fitness_cascade",
        "enable_failure_events",
        "enable_acceptance_gate",
    ):
        monkeypatch.delenv(f"EVOLVER_FF_{name.upper()}", raising=False)
    ff.invalidate_cache()
    try:
        for name in (
            "enable_fitness_cascade",
            "enable_failure_events",
            "enable_acceptance_gate",
        ):
            assert DEFAULT_FLAGS[name] is True, name
            assert is_enabled(name) is True, name
    finally:
        ff.invalidate_cache()


def test_acceptance_shadow_default_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOLVER_ACCEPTANCE_SHADOW", raising=False)
    assert ACCEPTANCE_SHADOW is True


def test_cascade_commands_filter_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        solidify_mod,
        "FITNESS_CASCADE_COMMANDS",
        [
            {"command": ["definitely-not-a-real-binary-xyz", "--version"]},
            {"command": [sys.executable, "-c", "print('ok')"]},
        ],
    )
    cmds = solidify_mod.get_fitness_cascade_commands()
    assert len(cmds) == 1
    assert cmds[0]["command"][0] == sys.executable


def test_cascade_commands_all_missing_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        solidify_mod,
        "FITNESS_CASCADE_COMMANDS",
        [{"command": ["definitely-not-a-real-binary-xyz"]}],
    )
    assert solidify_mod.get_fitness_cascade_commands() == []


def test_cascade_success_measured_score(git_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    set_flag("enable_acceptance_gate", False, persist=False)
    monkeypatch.setattr(
        solidify_mod,
        "FITNESS_CASCADE_COMMANDS",
        [{"command": [sys.executable, "-c", "print('ok')"]}],
    )
    write_state_for_solidify(_last_run())
    assert solidify()["ok"] is True
    evt = _last_event()
    assert evt["outcome"]["status"] == "success"
    assert evt["outcome"]["score"] == 1.0
    assert "unvalidated" not in evt["outcome"]


def test_unvalidated_success_score_is_none(git_ws: Path) -> None:
    set_flag("enable_acceptance_gate", False, persist=False)
    write_state_for_solidify(_last_run())
    assert solidify(skip_validation=True)["ok"] is True
    evt = _last_event()
    assert evt["outcome"]["status"] == "success"
    assert evt["outcome"]["score"] is None
    assert evt["outcome"]["unvalidated"] is True


def test_cascade_failure_score_partial_and_lineage(
    git_ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_flag("enable_acceptance_gate", False, persist=False)
    set_flag("enable_lineage_lessons", True, persist=False)
    # Two-stage cascade: stage 1 green, stage 2 hard-fails (non-pytest → 0.5).
    monkeypatch.setattr(
        solidify_mod,
        "FITNESS_CASCADE_COMMANDS",
        [
            {"command": [sys.executable, "-c", "print('ok')"]},
            {"command": [sys.executable, "-c", "import sys; sys.exit(1)"]},
        ],
    )
    write_state_for_solidify(_last_run())
    assert solidify()["ok"] is False
    evt = _last_event()
    assert evt["outcome"]["status"] == "failed"
    assert evt["outcome"]["score"] == 0.5
    # S26 fix: cascade failures now carry GEPA lineage fields too.
    assert evt.get("parent_event_id") is None  # no prior event in this workspace


# ---------------------------------------------------------------------------
# S26.3 strict-improvement gate (r_best ledger)
# ---------------------------------------------------------------------------


def _fitness_state() -> dict[str, Any]:
    from evolver.gep.fitness_state import load_domain

    return load_domain("cascade")


def test_solidify_records_fitness_verdict(git_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    set_flag("enable_acceptance_gate", False, persist=False)
    write_state_for_solidify(_last_run())
    assert solidify()["ok"] is True
    evt = _last_event()
    assert evt["fitness_gate"]["verdict"] == "baseline_established"
    assert _fitness_state()["r_best"] == 1.0

    # Second run, same score: strict > means no improvement — SHADOW: still ok.
    write_state_for_solidify(_last_run(run_id="run_s26_2"))
    assert solidify()["ok"] is True
    evt = _last_event()
    assert evt["fitness_gate"]["verdict"] == "no_improvement"


def test_fitness_gate_enforce_rolls_back_no_improvement(
    git_ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evolver.gep.fitness_state import record_measurement

    set_flag("enable_acceptance_gate", False, persist=False)
    record_measurement(1.0, source="solidify:seed")  # cascade r_best = 1.0
    # Cascade will measure 1.0 again → no_improvement → ENFORCE rejects.
    monkeypatch.setattr(solidify_mod, "FITNESS_GATE_ENFORCE", True)
    write_state_for_solidify(_last_run())
    result = solidify()
    assert result["ok"] is False
    assert result["error"] == "fitness_gate_no_improvement"
    assert _last_event()["outcome"]["error"] == "fitness_gate_no_improvement"
    # S27: enforced rejection lands wiki evidence too.
    from evolver.gep.wiki import wiki_dir

    impact = (wiki_dir() / "skill-impact.md").read_text(encoding="utf-8")
    assert "fitness_gate_no_improvement: gene_s26" in impact


def test_harmful_mutation_rejected_end_to_end(
    git_ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S26.3 acceptance #2: inject a HARMFUL mutation (one that breaks the
    validation cascade), the gate must veto it, roll the workspace back, and
    land the failure in the ledger — evidence chain: event + wiki + rollback.

    (Bench-val variant needs an agent executor and is tracked in 演进方案
    §8 移交; here the cascade stands in for the val surface, which is the
    default gating surface.)"""
    from evolver.gep.wiki import wiki_dir

    set_flag("enable_acceptance_gate", False, persist=False)
    # A harmful mutation: the touched file breaks every validation command.
    victim = git_ws / "breaks_here.txt"
    victim.write_text("about to be harmed\n", encoding="utf-8")
    _git(git_ws, "add", "-A")
    _git(git_ws, "-c", "commit.gpgsign=false", "commit", "-m", "victim")
    # A sentinel-based harmful detector: fails iff the file was harmed.
    detector = (
        "import pathlib,sys;"
        "sys.exit(1 if pathlib.Path('breaks_here.txt').read_text()=='harmed\\n' else 0)"
    )
    monkeypatch.setattr(
        solidify_mod,
        "FITNESS_CASCADE_COMMANDS",
        [{"command": [sys.executable, "-c", detector]}],
    )
    # the mutation: apply-proposal applies a harmful edit to the workspace
    from evolver.gep.proposal import apply_proposal, parse_proposal

    harmful = parse_proposal(
        {
            "action": "patch",
            "gene_id": "gene_harmful",
            "edits": [
                {
                    "op": "replace",
                    "file": "breaks_here.txt",
                    "target": "about to be harmed",
                    "content": "harmed",
                }
            ],
        }
    )
    assert apply_proposal(harmful, git_ws)["applied"] is True

    write_state_for_solidify(
        _last_run(run_id="run_harmful", selected_gene_id="gene_harmful", signals=["harm"])
    )
    result = solidify()
    assert result["ok"] is False
    assert result["error"] == "validation_failed"
    # rolled back: the harmful edit is gone from the working tree
    assert victim.read_text(encoding="utf-8") == "about to be harmed\n"
    # evidence chain: failed event landed, wiki entry landed
    evt = _last_event()
    assert evt["outcome"]["status"] == "failed"
    assert evt["outcome"]["error"] == "validation_failed"
    impact = (wiki_dir() / "skill-impact.md").read_text(encoding="utf-8")
    assert "validation_failed: gene_harmful" in impact
