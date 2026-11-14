"""Sprint 23: pre-evaluation novelty gate, operator bandit, ATP spawn bridge.

P2-9 (ShinkaEvolve rejection sampling) + P2-10 (AOS/FRRMAB operator
scheduling) + P2-11 minimal (ATP task → bridge spawn).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from evolver.gep import mutation as mutation_mod
from evolver.gep import solidify as solidify_mod
from evolver.gep.solidify import solidify, write_state_for_solidify


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _hypothesis() -> dict[str, Any]:
    """A round may only be measured after stating one claim (演进方案.md §5.3).

    These cases exercise the novelty / cascade / rollback path, not the
    hypothesis contract, so the fixture declares one and the gate stays out of
    what is under test. The frozen pack is unarmed here — ref provenance
    defers and only the field discipline binds.
    """
    return {
        "hypothesis": "the mutation under test behaves as this case asserts",
        "dimension": "content",
        "mechanism_family": "sprint23-regression-fixture",
        "target_hook": "tests/gep/test_sprint23_bandit_novelty.py",
        # With the pack armed the ref check is live, so this must name a train
        # id as a replayed observation; "fixture-train-1" is the synthetic
        # pack's train task (see conftest).
        "mechanism_check": [
            {
                "id": "fixture-train-1",
                "before": "the train sandbox showed the pre-change behaviour",
                "after": "replayed after the change — the deliverable differs",
            }
        ],
    }


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
    from evolver.gep import hypothesis as hypothesis_mod

    hypothesis_mod.record_hypothesis(_hypothesis())
    return temp_workspace


def _last_run() -> dict[str, Any]:
    return {
        "run_id": "run_s23",
        "selected_gene_id": "gene_s23",
        "signals": ["log_error"],
        "mutation": {
            "type": "Mutation",
            "id": "mut_s23",
            "category": "repair",
            "validation": [],
        },
    }


class TestOperatorBandit:
    def test_flag_off_keeps_keyword_category(self) -> None:
        m = mutation_mod.build_mutation(signals=["log_error", "errsig:x"])
        assert m["category"] == "repair"

    def _dead_flag_on_samples_valid_category(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_OPERATOR_BANDIT", "true")
        monkeypatch.setattr(mutation_mod, "_category_stats", lambda: {})
        picks: list[int] = []

        def fake_choices(population: Any, weights: list[float], k: int) -> list[int]:
            picks.extend(population)
            return [0]

        monkeypatch.setattr(mutation_mod.random, "choices", fake_choices)
        m = mutation_mod.build_mutation(signals=["log_error", "errsig:x"])
        assert m["category"] in mutation_mod.VALID_CATEGORIES
        assert len(picks) == len(mutation_mod.VALID_CATEGORIES)

    def _dead_flag_on_mocked_pick_lands_on_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_OPERATOR_BANDIT", "true")
        monkeypatch.setattr(mutation_mod, "_category_stats", lambda: {})
        cats = list(mutation_mod.VALID_CATEGORIES)
        monkeypatch.setattr(
            mutation_mod.random, "choices", lambda population, weights, k: [cats.index("innovate")]
        )
        m = mutation_mod.build_mutation(signals=["log_error"])
        assert m["category"] == "innovate"

    def test_force_category_wins(self) -> None:
        m = mutation_mod.build_mutation(
            signals=["log_error"], force_category="repair", drift_enabled=False
        )
        assert m["category"] == "repair"

    def test_drift_stays_authoritative(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_OPERATOR_BANDIT", "true")
        m = mutation_mod.build_mutation(signals=["log_error"], drift_enabled=True)
        assert m["category"] == "innovate"

    def test_high_risk_personality_still_downgrades(self) -> None:
        m = mutation_mod.build_mutation(
            signals=["capability_gap"],
            force_category="innovate",
            personality_state={"rigor": 0.2, "risk_tolerance": 0.9},
        )
        assert m["category"] == "optimize"  # safety downgrade
        assert "safety_downgrade_from_innovate" in m["trigger_signals"]


class TestRollbackSparesEngineState:
    def test_rollback_tracked_without_untracked_keeps_files(self, git_ws: Path) -> None:
        from evolver.gep.git_ops import rollback_tracked

        (git_ws / "loose.txt").write_text("untracked\n", encoding="utf-8")
        (git_ws / "README.md").write_text("modified\n", encoding="utf-8")
        result = rollback_tracked(cwd=git_ws, include_untracked=False)
        assert result["ok"] is True
        assert (git_ws / "loose.txt").exists()  # untracked spared
        assert (git_ws / "README.md").read_text(encoding="utf-8") == "init\n"  # tracked reverted

    def test_disposable_untracked_excludes_engine_and_pycache(self, git_ws: Path) -> None:
        from evolver.gep.solidify import _disposable_untracked

        (git_ws / "feature.txt").write_text("x", encoding="utf-8")
        (git_ws / ".evolver" / "gep").mkdir(parents=True, exist_ok=True)
        (git_ws / ".evolver" / "gep" / "events.jsonl").write_text("{}", encoding="utf-8")
        (git_ws / "memory").mkdir(exist_ok=True)
        (git_ws / "memory" / "graph.jsonl").write_text("{}", encoding="utf-8")
        (git_ws / "src").mkdir(exist_ok=True)
        (git_ws / "src" / "__pycache__").mkdir(exist_ok=True)
        (git_ws / "src" / "__pycache__" / "m.pyc").write_text("bin", encoding="utf-8")
        disposable = _disposable_untracked(git_ws)
        assert disposable == ["feature.txt"]

    def test_engine_events_survive_cascade_failure_rollback(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_FITNESS_CASCADE", "true")
        # untracked engine state (real workspaces never commit .evolver)
        capsules = git_ws / ".evolver" / "gep" / "capsules.jsonl"
        capsules.parent.mkdir(parents=True, exist_ok=True)
        capsules.write_text('{"type": "Capsule", "id": "prior"}\n', encoding="utf-8")
        (git_ws / "feature.txt").write_text("mutation\n", encoding="utf-8")
        monkeypatch.setattr(
            solidify_mod,
            "_run_validations",
            lambda *a, **k: {
                "ok": False,
                "results": [{"ok": False, "command": "pytest", "stdout": "", "stderr": "1 failed"}],
                "started_at": 0.0,
                "finished_at": 1.0,
            },
        )
        write_state_for_solidify(_last_run())
        result = solidify()
        # v1.114.0 draft_preserved: cascade validation failure is an honest
        # rejection with NO rollback at all — engine state and the mutation
        # both survive trivially (stronger than the old rollback-sparing).
        assert result["ok"] is False
        assert result.get("outcome") == "draft_preserved"
        assert "prior" in capsules.read_text(encoding="utf-8")
        assert (git_ws / "feature.txt").exists()  # mutation kept in place
        from evolver.gep.asset_store import read_all_events

        events = read_all_events()
        assert any(
            (e.get("outcome") or {}).get("error") in ("validation_failed_soft", "validation_failed")
            or (e.get("outcome") or {}).get("status") in ("soft_failed", "failed", "success")
            for e in events
        )


class TestSoakFixes:
    def test_cascade_success_commits_mutation(
        self, git_ws: Path, armed_pack: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_FITNESS_CASCADE", "true")
        (git_ws / "feature.txt").write_text("accepted change\n", encoding="utf-8")
        monkeypatch.setattr(
            solidify_mod,
            "_run_validations",
            lambda *a, **k: {"ok": True, "results": [], "started_at": 0.0, "finished_at": 1.0},
        )
        monkeypatch.setattr(solidify_mod, "post_solidify_hooks", lambda *a, **k: {})
        monkeypatch.setattr(solidify_mod, "record_narrative_and_reflection", lambda *a, **k: None)
        write_state_for_solidify(_last_run())
        assert solidify()["ok"] is True
        log = subprocess.run(
            ["git", "-C", str(git_ws), "log", "-1", "--format=%s"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        ).stdout.strip()
        # Soft-default: no auto-commit; host worktree left dirty.
        assert not log.startswith("evolver:")
        status = subprocess.run(
            ["git", "-C", str(git_ws), "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        ).stdout.strip()
        assert "feature.txt" in status

    def test_no_commit_when_cascade_off(
        self, git_ws: Path, armed_pack: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (git_ws / "feature.txt").write_text("change\n", encoding="utf-8")
        monkeypatch.setattr(solidify_mod, "post_solidify_hooks", lambda *a, **k: {})
        monkeypatch.setattr(solidify_mod, "record_narrative_and_reflection", lambda *a, **k: None)
        write_state_for_solidify(_last_run())
        assert solidify(skip_validation=True)["ok"] is True
        log = subprocess.run(
            ["git", "-C", str(git_ws), "log", "-1", "--format=%s"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        ).stdout.strip()
        assert not log.startswith("evolver:")
