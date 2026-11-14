"""Sprint 22/23 coverage gaps — edge paths the soak/E2E work added but the
suite never pinned (dispatch lineage wiring, commit failure paths, bandit
mean term, containment boundary, inert-ban probation, psutil failure...).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from evolver.gep import solidify as solidify_mod
from evolver.gep.solidify import solidify, write_state_for_solidify


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    )


@pytest.fixture
def git_ws(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(temp_workspace))
    gep = temp_workspace / ".evolver" / "gep"
    gep.mkdir(parents=True, exist_ok=True)
    (gep / "events.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setenv("GEP_ASSETS_DIR", str(gep))
    _git(temp_workspace, "init")
    _git(temp_workspace, "config", "user.email", "test@test.com")
    _git(temp_workspace, "config", "user.name", "Test")
    (temp_workspace / "README.md").write_text("init\n", encoding="utf-8")
    _git(temp_workspace, "add", "-A")
    _git(temp_workspace, "-c", "commit.gpgsign=false", "commit", "-m", "init")
    return temp_workspace


def _last_run() -> dict[str, Any]:
    return {
        "run_id": "run_gaps",
        "selected_gene_id": "gene_gaps",
        "signals": ["log_error"],
        "mutation": {"type": "Mutation", "id": "mut_gaps", "category": "repair", "validation": []},
    }


class TestCommitMutationEdges:
    def test_no_targets_returns_false(self, git_ws: Path) -> None:
        assert solidify_mod._commit_mutation(git_ws, "noop") is False

    # armed_pack + declared_hypothesis: §5.3 and §5.2 gate the publish, and
    # this case pins what happens AFTER they let the round through — a dead git
    # must not turn a successful round into a failure.
    def test_git_failure_returns_false_but_solidify_survives(
        self,
        git_ws: Path,
        monkeypatch: pytest.MonkeyPatch,
        armed_pack: dict[str, Any],
        declared_hypothesis: dict[str, Any],
    ) -> None:
        from evolver.gep import git_ops

        monkeypatch.setenv("EVOLVER_FF_ENABLE_FITNESS_CASCADE", "true")
        (git_ws / "feature.txt").write_text("change\n", encoding="utf-8")
        real_run_cmd = git_ops.run_cmd

        def selective_run_cmd(args: Any, *a: Any, **k: Any) -> str:
            if args and args[0] in ("add", "commit"):
                raise RuntimeError("git down")
            return real_run_cmd(args, *a, **k)

        monkeypatch.setattr("evolver.gep.git_ops.run_cmd", selective_run_cmd)
        monkeypatch.setattr(
            solidify_mod,
            "_run_validations",
            lambda *a, **k: {"ok": True, "results": [], "started_at": 0.0, "finished_at": 1.0},
        )
        monkeypatch.setattr(solidify_mod, "post_solidify_hooks", lambda *a, **k: {})
        monkeypatch.setattr(solidify_mod, "record_narrative_and_reflection", lambda *a, **k: None)
        write_state_for_solidify(_last_run())
        assert solidify_mod._commit_mutation(git_ws, "probe") is False
        result = solidify()
        assert result["ok"] is True  # commit failure never fails solidify


class TestPytestRateDeselected:
    def test_deselected_not_in_denominator(self) -> None:
        assert solidify_mod._parse_pytest_rate("2900 passed, 50 deselected in 3s") == 1.0


class TestHardModeKeepsUntracked:
    def test_hard_rollback_spares_untracked(self, git_ws: Path) -> None:
        from evolver.gep.git_ops import rollback_tracked

        (git_ws / "loose.txt").write_text("untracked\n", encoding="utf-8")
        (git_ws / "README.md").write_text("modified\n", encoding="utf-8")
        result = rollback_tracked(mode="hard", cwd=git_ws, include_untracked=False)
        assert result["ok"] is True
        assert (git_ws / "loose.txt").exists()  # hard reset never deletes untracked
        assert (git_ws / "README.md").read_text(encoding="utf-8") == "init\n"
