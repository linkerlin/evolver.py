"""P0-3 判据三 (算子即基因 v1.114.0, 支柱一): the vault never sees a failure.

Any round whose pytest/mypy/ruff-style validation fails, or whose fitness
verdict is a regression/drop against the baseline, must leave the positive
gene vault at strictly ``+0`` — while the worktree patch survives in place
(draft preserved) and the failure is honestly recorded on the failure side.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from evolver.bench import frozen_gate as gate_mod
from evolver.gep import solidify as solidify_mod
from evolver.gep.asset_store import load_genes
from evolver.gep.solidify import solidify, write_state_for_solidify


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _last_run() -> dict[str, Any]:
    return {
        "run_id": "run_dual_track",
        "selected_gene_id": "gene_dual_track",
        "signals": ["test"],
        "mutation": {
            "type": "Mutation",
            "id": "mut_dual_track",
            "category": "repair",
            "validation": [],
        },
    }


@pytest.fixture
def git_ws(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(temp_workspace))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    gep = temp_workspace / ".evolver" / "gep"
    gep.mkdir(parents=True, exist_ok=True)
    (gep / "events.jsonl").write_text("", encoding="utf-8")
    evo = temp_workspace / "memory" / "evolution"
    evo.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("GEP_ASSETS_DIR", str(gep))
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))
    monkeypatch.setenv("EVOLVER_HOME", str(temp_workspace / ".evomap-home"))
    from evolver.gep.acceptance import solidify_hook as hook_mod

    monkeypatch.setattr(hook_mod, "gate_for_solidify", lambda _r, _c: None)
    from evolver.gep import hypothesis as hypothesis_mod

    hypothesis_mod.record_hypothesis(
        {
            "hypothesis": "the executor misreads the spec clause",
            "dimension": "content",
            "mechanism_family": "spec-literal",
            "target_hook": "dispatch prompt section 2",
            "mechanism_check": [
                {
                    "id": "spec-pipe-0",
                    "before": "the train task's sandbox showed the old reading",
                    "after": "replayed after the change — the deliverable differs",
                }
            ],
        }
    )
    _git(temp_workspace, "init")
    _git(temp_workspace, "config", "user.email", "test@test.com")
    _git(temp_workspace, "config", "user.name", "Test")
    (temp_workspace / "README.md").write_text("init\n", encoding="utf-8")
    _git(temp_workspace, "add", "-A")
    _git(temp_workspace, "-c", "commit.gpgsign=false", "commit", "-m", "init")
    return temp_workspace


def _vault_count() -> int:
    return len(load_genes())


def test_red_validation_freezes_the_vault(git_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A pytest-style red round: ok=False draft, worktree kept, vault +0."""
    monkeypatch.setattr(
        solidify_mod,
        "FITNESS_CASCADE_COMMANDS",
        [{"command": [sys.executable, "-c", "import sys; sys.exit(1)"]}],
    )
    before = _vault_count()
    write_state_for_solidify(_last_run())
    result = solidify()
    assert result["ok"] is False
    assert result["outcome"] == "draft_preserved"
    assert _vault_count() == before, "a red validation must not mint vault assets"


def test_bench_regression_freezes_the_vault(git_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A baseline-regression round: honest rejection, worktree kept, vault +0."""
    monkeypatch.setattr(
        gate_mod,
        "gate_verdict",
        lambda **_kw: {
            "armed": True,
            "pack": "/frozen/charter-pack.tasks.json",
            "digest": "abc123",
            "split": "val",
            "score": 0.4,
            "baseline": 1.0,
            "verdict": "reject",
            "accept": False,
            "reason": "regression",
        },
    )
    before = _vault_count()
    write_state_for_solidify(_last_run())
    result = solidify(skip_validation=True)
    assert result["ok"] is False
    assert result["outcome"] == "draft_preserved"
    assert result["error"] == "bench_pack_rejected"
    assert _vault_count() == before, "a regression round must not mint vault assets"


def test_draft_patch_survives_in_worktree(git_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The draft contract: the host's uncommitted work is never destroyed."""
    patched = git_ws / "draft.txt"
    patched.write_text("work in progress\n", encoding="utf-8")
    monkeypatch.setattr(
        gate_mod,
        "gate_verdict",
        lambda **_kw: {
            "armed": True,
            "digest": "d",
            "score": 0.1,
            "baseline": 1.0,
            "verdict": "reject",
            "accept": False,
            "reason": "drop",
        },
    )
    write_state_for_solidify(_last_run())
    result = solidify(skip_validation=True)
    assert result["ok"] is False
    assert result["outcome"] == "draft_preserved"
    assert patched.read_text(encoding="utf-8") == "work in progress\n"
    assert result.get("rejected_stash"), "a防丢 backup must exist"


def test_distill_then_failed_solidify_retracts_staged_assets(git_ws: Path) -> None:
    """Round-121 review pin for the REAL MCP loop: swarm_distill installs
    genes/capsules BEFORE solidify judges — so a draft_preserved settle must
    retract that run's staged assets, or the vault absorbs unvalidated work
    (the leak test_dual_track_vault_freeze originally missed)."""
    from evolver.gep.asset_store import load_capsules, load_genes, retract_distilled_assets
    from evolver.gep.distill import install_distilled
    from evolver.gep.solidify import write_state_for_solidify

    run_id = "run_leak_check"
    write_state_for_solidify(
        {
            "run_id": run_id,
            "selected_gene_id": "gene_leak",
            "signals": ["log_error"],
            "mutation": {"type": "Mutation", "id": "m_leak", "category": "repair"},
        }
    )

    before_g = len(load_genes())
    before_c = len(load_capsules())
    install_distilled(
        {
            "genes": [
                {
                    "type": "Gene",
                    "id": "gene_distilled_leak1",
                    "category": "repair",
                    "signals_match": ["log_error"],
                    "strategy": ["staged"],
                }
            ],
            "capsules": [{"type": "Capsule", "id": "cap_leak1", "summary": "staged capsule"}],
        }
    )
    assert len(load_genes()) == before_g + 1  # staged (visible pre-judgment)
    assert len(load_capsules()) == before_c + 1

    # The settle rejects → retraction → the vault sees strictly zero new rows.
    retract_distilled_assets(run_id)
    assert len(load_genes()) == before_g, "staged gene must vanish on draft_preserved"
    assert len(load_capsules()) == before_c, "staged capsule must vanish on draft_preserved"
