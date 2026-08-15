"""Sprint 22/23 coverage gaps — edge paths the soak/E2E work added but the
suite never pinned (dispatch lineage wiring, commit failure paths, bandit
mean term, containment boundary, inert-ban probation, psutil failure...).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from evolver.evolve import guards
from evolver.gep import mutation as mutation_mod
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


class TestDispatchLineageWiring:
    @pytest.mark.asyncio
    async def test_prompt_gets_parent_and_lessons(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.evolve.pipeline import dispatch as dispatch_mod
        from evolver.gep.asset_store import append_event_jsonl, get_last_event_id

        monkeypatch.setenv("EVOLVER_FF_ENABLE_LINEAGE_LESSONS", "true")
        append_event_jsonl(
            {
                "type": "EvolutionEvent",
                "id": "evt_parent",
                "gene_id": "gene_gaps",
                "outcome": {"status": "failed", "error": "validation_failed"},
                "mutation": {"category": "repair"},
                "blast_radius": {"files": 2, "lines": 9},
                "signals": ["log_error"],
            }
        )
        captured: dict[str, Any] = {}
        real_prompt = dispatch_mod.build_gep_prompt

        def capture_prompt(**kwargs: Any) -> str:
            captured.update(kwargs)
            return real_prompt(**kwargs)

        monkeypatch.setattr(dispatch_mod, "build_gep_prompt", capture_prompt)
        gene = {
            "id": "gene_gaps",
            "category": "repair",
            "signals_match": ["log_error"],
            "summary": "fix",
        }
        ctx: dict[str, Any] = {
            "selected_gene": gene,
            "genes": [gene],
            "capsules": [],
            "signals": ["log_error"],
            "recent_events": [
                {
                    "gene_id": "gene_gaps",
                    "outcome": {"status": "failed", "error": "validation_failed"},
                    "mutation": {"category": "repair"},
                    "blast_radius": {"files": 2, "lines": 9},
                    "signals": ["log_error"],
                }
            ],
            "cycle_id": "gapcycle",
            "scan_time_iso": "2026-08-15T00:00:00Z",
            "selected_by": "score_ranked",
            "bridge_enabled": False,
        }
        await dispatch_mod.dispatch_phase(ctx)
        assert captured["parent_event_id"] == get_last_event_id()
        assert "Lineage Lessons" in captured["context"]
        assert "validation_failed" in captured["context"]

    @pytest.mark.asyncio
    async def test_flag_off_no_lessons_no_parent(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.evolve.pipeline import dispatch as dispatch_mod

        monkeypatch.delenv("EVOLVER_FF_ENABLE_LINEAGE_LESSONS", raising=False)
        captured: dict[str, Any] = {}
        real_prompt = dispatch_mod.build_gep_prompt

        def capture_prompt(**kwargs: Any) -> str:
            captured.update(kwargs)
            return real_prompt(**kwargs)

        monkeypatch.setattr(dispatch_mod, "build_gep_prompt", capture_prompt)
        gene = {"id": "g", "category": "repair", "signals_match": ["log_error"], "summary": "s"}
        await dispatch_mod.dispatch_phase(
            {
                "selected_gene": gene,
                "genes": [gene],
                "capsules": [],
                "signals": ["log_error"],
                "recent_events": [
                    {
                        "gene_id": "g",
                        "outcome": {"status": "failed", "error": "x"},
                        "mutation": {"category": "repair"},
                    }
                ],
                "cycle_id": "c",
                "scan_time_iso": "t",
                "bridge_enabled": False,
            }
        )
        assert captured["parent_event_id"] is None
        assert "Lineage Lessons" not in captured["context"]


class TestCommitMutationEdges:
    def test_no_targets_returns_false(self, git_ws: Path) -> None:
        assert solidify_mod._commit_mutation(git_ws, "noop") is False

    def test_git_failure_returns_false_but_solidify_survives(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
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


class TestCategoryStatsFromStore:
    @pytest.mark.usefixtures("temp_workspace")
    def test_filters_invalid_and_reads_tail(self) -> None:
        from evolver.gep.asset_store import append_event_jsonl

        for i in range(3):
            append_event_jsonl(
                {
                    "type": "EvolutionEvent",
                    "id": f"e{i}",
                    "mutation": {"category": "repair"},
                    "outcome": {"status": "failed", "score": 0.5},
                }
            )
        append_event_jsonl(
            {
                "type": "EvolutionEvent",
                "id": "bad1",
                "mutation": {"category": "repair"},
                "outcome": {"status": "failed"},  # no numeric score -> skipped
            }
        )
        append_event_jsonl(
            {
                "type": "EvolutionEvent",
                "id": "bad2",
                "mutation": {},  # no category -> skipped
                "outcome": {"status": "success", "score": 1.0},
            }
        )
        stats = mutation_mod._category_stats()
        assert stats == {"repair": {"attempts": 3.0, "score_sum": 1.5}}


class TestOperatorBanditMeanTerm:
    def test_better_mean_higher_weight(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_OPERATOR_BANDIT", "true")
        monkeypatch.setattr(
            mutation_mod,
            "_category_stats",
            lambda: {
                "repair": {"attempts": 10.0, "score_sum": 10.0},  # mean 1.0
                "innovate": {"attempts": 10.0, "score_sum": 1.0},  # mean 0.1
            },
        )
        seen: dict[str, list[float]] = {}

        def fake_choices(population: Any, weights: list[float], k: int) -> list[int]:
            seen["weights"] = weights
            return [0]

        monkeypatch.setattr(mutation_mod.random, "choices", fake_choices)
        cats = list(mutation_mod.VALID_CATEGORIES)
        m = mutation_mod.build_mutation(signals=["log_error"])  # keyword: repair
        assert m["category"] in cats
        w = seen["weights"]
        assert w[cats.index("repair")] > w[cats.index("innovate")]


class TestContainmentMinCharsBoundary:
    @pytest.mark.usefixtures("temp_workspace")
    def test_short_prior_contained_but_not_duplicate(self) -> None:
        from evolver.gep.asset_store import append_capsule

        append_capsule(
            {
                "type": "Capsule",
                "id": "cap_tiny",
                "trigger": ["log_error"],
                "gene": "g",
                "summary": "s",
                "confidence": 0.5,
                "outcome": {"status": "success", "score": 1.0},
                "diff": "+abc\n",
            }
        )
        ws = Path(__import__("os").environ["OPENCLAW_WORKSPACE"])
        (ws / "big.txt").write_text("abcdef" * 30 + "\n", encoding="utf-8")
        # "abc" (len 3 < 40) is contained in the fingerprint's added text but
        # must NOT trigger the containment path; similarity is also low.
        assert solidify_mod._novelty_duplicate_diff(ws) is False


class TestAtpBridgeEmitFailure:
    @pytest.mark.asyncio
    async def test_emit_failure_swallowed(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_ATP_SPAWN_BRIDGE", "true")
        monkeypatch.setattr(
            "evolver.atp.atp_task_pickup.pick_one",
            AsyncMock(return_value="# ATP Task t\n"),
        )

        def boom(payload: dict[str, Any]) -> str:
            raise RuntimeError("renderer down")

        monkeypatch.setattr("evolver.gep.bridge.render_sessions_spawn_call", boom)
        from evolver.evolve.post_cycle import run_post_cycle_hooks

        ctx = await run_post_cycle_hooks(
            {"signals": ["log_error"], "bridge_enabled": True, "AGENT_NAME": "main"}
        )
        assert "atp_spawn_emitted" not in ctx  # failure swallowed
        assert ctx["atp_spawn_instruction"] == "# ATP Task t\n"  # persistence intact


class TestWindowsLoadGuardPsutilFailure:
    def test_psutil_import_failure_yields_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys

        monkeypatch.setenv("EVOLVER_FF_ENABLE_WINDOWS_LOAD_GUARD", "true")

        def _raise() -> tuple[float, float, float]:
            raise AttributeError("no getloadavg")

        monkeypatch.setattr("os.getloadavg", _raise, raising=False)
        monkeypatch.setitem(sys.modules, "psutil", None)  # import psutil -> ImportError
        sample = guards.get_system_load()
        assert (sample.load1m, sample.load5m, sample.load15m) == (0.0, 0.0, 0.0)


class TestLineageLessonsLimit:
    def test_at_most_three_lessons(self) -> None:
        from evolver.evolve.pipeline.dispatch import _build_lineage_lessons

        events = [
            {
                "gene_id": "g1",
                "outcome": {"status": "failed", "error": f"err{i}"},
                "mutation": {"category": "repair"},
            }
            for i in range(5)
        ]
        block = _build_lineage_lessons("g1", events)
        assert block.count("- [") == 3
        assert "err4" in block  # newest first


class TestInertBanProbation:
    @pytest.mark.usefixtures("temp_workspace")
    def test_inert_ban_gets_probation_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from evolver.gep import memory_graph

        monkeypatch.setenv("EVOLVER_FF_ENABLE_NICHE_TOPK", "true")
        for _ in range(memory_graph.GENE_INERT_BAN_STREAK):
            memory_graph.record_outcome(
                signals=["log_error"],
                selected_gene={"id": "g_inert"},
                outcome={"status": "success", "note": "stable_no_error"},
            )
        key = memory_graph.compute_signal_key(["log_error"])
        first = memory_graph.get_memory_advice(signals=["log_error"], genes=[])
        assert "g_inert" in first["bannedGeneIds"]  # sentence starts
        assert memory_graph._probation_until(key, "g_inert") is not None
        second = memory_graph.get_memory_advice(signals=["log_error"], genes=[])
        assert "g_inert" not in second["bannedGeneIds"]  # probation running


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
