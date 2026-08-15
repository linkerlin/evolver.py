"""Sprint 23: pre-evaluation novelty gate, operator bandit, ATP spawn bridge.

P2-9 (ShinkaEvolve rejection sampling) + P2-10 (AOS/FRRMAB operator
scheduling) + P2-11 minimal (ATP task → bridge spawn).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from evolver.gep import mutation as mutation_mod
from evolver.gep import solidify as solidify_mod
from evolver.gep.solidify import solidify, write_state_for_solidify


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


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


class TestDiffSimilarity:
    def test_identical(self) -> None:
        assert solidify_mod._diff_similarity("abc def\n+1", "abc def\n+1") == pytest.approx(1.0)

    def test_disjoint(self) -> None:
        assert solidify_mod._diff_similarity("aaaa", "zzzz") < 0.3

    def test_empty(self) -> None:
        assert solidify_mod._diff_similarity("", "x") == 0.0

    def test_bare_content_matches_diff_form(self) -> None:
        assert (
            solidify_mod._diff_similarity("change\n", "+ change\n- old\n") > 0.5
            or solidify_mod._diff_similarity("change\n", "diff --git a/f b/f\n@@\n+change\n") > 0.5
        )


class TestNoveltyGate:
    def _apply_change(self, ws: Path) -> None:
        (ws / "feature.txt").write_text("change\n", encoding="utf-8")

    def _seed_capsule(self, diff: str) -> None:
        from evolver.gep.asset_store import append_capsule

        append_capsule(
            {
                "type": "Capsule",
                "id": "cap_dup_1",
                "trigger": ["log_error"],
                "gene": "gene_s23",
                "summary": "prior fix",
                "confidence": 0.5,
                "outcome": {"status": "success", "score": 1.0},
                "diff": diff,
            }
        )

    def test_duplicate_rejected_before_cascade(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_FITNESS_CASCADE", "true")
        monkeypatch.setenv("EVOLVER_FF_ENABLE_NOVELTY_GATE", "true")
        self._apply_change(git_ws)
        self._seed_capsule("diff --git a/feature.txt b/feature.txt\n+change\n")
        ran: list[bool] = []
        monkeypatch.setattr(
            solidify_mod,
            "_run_validations",
            lambda *a, **k: ran.append(True) or {"ok": True, "results": []},
        )
        write_state_for_solidify(_last_run())
        result = solidify()
        assert result["ok"] is False
        assert result["error"] == "novelty_duplicate"
        assert ran == []  # cascade never paid for
        from evolver.gep.asset_store import read_all_events

        ev = read_all_events()[-1]
        assert ev["outcome"]["error"] == "novelty_duplicate"
        assert not (git_ws / "feature.txt").exists()  # rolled back (cwd-correct)

    def test_novel_diff_proceeds(self, git_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_FITNESS_CASCADE", "true")
        monkeypatch.setenv("EVOLVER_FF_ENABLE_NOVELTY_GATE", "true")
        self._apply_change(git_ws)
        self._seed_capsule("+completely different change elsewhere")
        ran: list[bool] = []
        monkeypatch.setattr(
            solidify_mod,
            "_run_validations",
            lambda *a, **k: (
                ran.append(True)
                or {"ok": True, "results": [], "started_at": 0.0, "finished_at": 1.0}
            ),
        )
        monkeypatch.setattr(solidify_mod, "post_solidify_hooks", lambda *a, **k: {})
        monkeypatch.setattr(solidify_mod, "record_narrative_and_reflection", lambda *a, **k: None)
        write_state_for_solidify(_last_run())
        result = solidify()
        assert result["ok"] is True
        assert ran == [True]

    def test_flag_off_runs_cascade_anyway(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_FITNESS_CASCADE", "true")
        self._apply_change(git_ws)
        self._seed_capsule("diff --git a/feature.txt b/feature.txt\n+change\n")
        ran: list[bool] = []
        monkeypatch.setattr(
            solidify_mod,
            "_run_validations",
            lambda *a, **k: (
                ran.append(True)
                or {"ok": True, "results": [], "started_at": 0.0, "finished_at": 1.0}
            ),
        )
        monkeypatch.setattr(solidify_mod, "post_solidify_hooks", lambda *a, **k: {})
        monkeypatch.setattr(solidify_mod, "record_narrative_and_reflection", lambda *a, **k: None)
        write_state_for_solidify(_last_run())
        assert solidify()["ok"] is True
        assert ran == [True]


class TestOperatorBandit:
    def test_flag_off_keeps_keyword_category(self) -> None:
        m = mutation_mod.build_mutation(signals=["log_error", "errsig:x"])
        assert m["category"] == "repair"

    def test_flag_on_samples_valid_category(self, monkeypatch: pytest.MonkeyPatch) -> None:
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

    def test_flag_on_mocked_pick_lands_on_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_OPERATOR_BANDIT", "true")
        monkeypatch.setattr(mutation_mod, "_category_stats", lambda: {})
        cats = list(mutation_mod.VALID_CATEGORIES)
        monkeypatch.setattr(
            mutation_mod.random, "choices", lambda population, weights, k: [cats.index("innovate")]
        )
        m = mutation_mod.build_mutation(signals=["log_error"])
        assert m["category"] == "innovate"

    def test_force_category_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_OPERATOR_BANDIT", "true")
        monkeypatch.setattr(mutation_mod, "_category_stats", lambda: {})
        monkeypatch.setattr(
            mutation_mod.random,
            "choices",
            lambda population, weights, k: (_ for _ in ()).throw(AssertionError("must not sample")),
        )
        m = mutation_mod.build_mutation(
            signals=["log_error"], force_category="repair", drift_enabled=False
        )
        assert m["category"] == "repair"

    def test_drift_stays_authoritative(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_OPERATOR_BANDIT", "true")
        m = mutation_mod.build_mutation(signals=["log_error"], drift_enabled=True)
        assert m["category"] == "innovate"

    def test_high_risk_personality_still_downgrades(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_OPERATOR_BANDIT", "true")
        monkeypatch.setattr(mutation_mod, "_category_stats", lambda: {})
        cats = list(mutation_mod.VALID_CATEGORIES)
        monkeypatch.setattr(
            mutation_mod.random, "choices", lambda population, weights, k: [cats.index("innovate")]
        )
        m = mutation_mod.build_mutation(
            signals=["capability_gap"],
            personality_state={"rigor": 0.2, "risk_tolerance": 0.9},
        )
        assert m["category"] == "optimize"  # safety downgrade after sampling
        assert "safety_downgrade_from_innovate" in m["trigger_signals"]


class TestAtpSpawnBridge:
    @pytest.mark.asyncio
    async def test_bridge_spawn_emitted(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        spawn = "# ATP Task t-9\nQuestion: do the thing\n"
        monkeypatch.setenv("EVOLVER_FF_ENABLE_ATP_SPAWN_BRIDGE", "true")
        monkeypatch.setattr(
            "evolver.atp.atp_task_pickup.pick_one",
            AsyncMock(return_value=spawn),
        )
        from evolver.evolve.post_cycle import run_post_cycle_hooks

        ctx = await run_post_cycle_hooks(
            {"signals": ["log_error"], "bridge_enabled": True, "AGENT_NAME": "main"}
        )
        assert ctx["atp_spawn_emitted"] is True
        out = capsys.readouterr().out
        assert "sessions_spawn" in out and "ATP Task t-9" in out

    @pytest.mark.asyncio
    async def test_no_bridge_no_emit(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_ATP_SPAWN_BRIDGE", "true")
        monkeypatch.setattr(
            "evolver.atp.atp_task_pickup.pick_one",
            AsyncMock(return_value="# ATP Task t-9\n"),
        )
        from evolver.evolve.post_cycle import run_post_cycle_hooks

        ctx = await run_post_cycle_hooks({"signals": ["log_error"], "bridge_enabled": False})
        assert "atp_spawn_emitted" not in ctx
        assert "sessions_spawn" not in capsys.readouterr().out


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
                "results": [
                    {"ok": False, "command": "pytest", "stdout": "", "stderr": "1 failed"}
                ],
                "started_at": 0.0,
                "finished_at": 1.0,
            },
        )
        write_state_for_solidify(_last_run())
        result = solidify()
        assert result["ok"] is False
        assert result["error"] == "validation_failed"
        # untracked engine memory survived; mutation file rolled back
        assert "prior" in capsules.read_text(encoding="utf-8")
        assert not (git_ws / "feature.txt").exists()
        # failure event still lands (appended to events.jsonl)
        from evolver.gep.asset_store import read_all_events

        assert read_all_events()[-1]["outcome"]["error"] == "validation_failed"
