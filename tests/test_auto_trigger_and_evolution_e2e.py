"""End-to-end tests for Auto-Triggering and Real, Reliable, Beneficial Auto-Evolution.

Covers:
1. Auto-Triggering E2E:
   - File adapter hooks (signal_detect.py & session_end.py CLI stdin/stdout JSON)
   - In-process MCP hook bridge (swarm_hook_event)
   - Trajectory counter accumulation & cursor.reminder(by_trajectory=True)
   - Pending signal injection -> WFQ + problem_value ranking in signals_phase
   - DailyBudget environment variable caps & guard preflight enforcement
   - Idle scheduler intensity throttling (signal_only vs deep)
2. Auto-Evolution E2E (Multi-Round Closed Loop):
   - Round 1 (Reliable Rollback on Harmful Mutation):
     A broken mutation fails real pytest validation -> atomic git rollback ->
     VariantArchiveEntry recorded -> EpisodeRecord written with attribution='hurt'.
   - Round 2 (Adaptive Pivot & Beneficial Solidification):
     Next tick detects prior 'hurt' episode -> activates autopoiesis_repair_bias ->
     cools down offending gene -> selects repair gene -> applies structured
     INV x DOM GeneProposal via swarm_propose -> passes real pytest validation ->
     commits beneficial fix -> records EpisodeRecord with attribution='helped'
     and positive behavioral contrast (newly_passed).
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from evolver.adapters.scripts import session_end, signal_detect
from evolver.evolve.guards import run_preflight_checks
from evolver.evolve.pipeline.dispatch import dispatch_phase
from evolver.evolve.pipeline.select import select_phase
from evolver.evolve.pipeline.signals import signals_phase
from evolver.gep import cursor, episode_record
from evolver.gep.asset_store import upsert_gene


def save_genes(genes: list[dict[str, Any]]) -> None:
    for g in genes:
        upsert_gene(g)


from evolver.gep.trigger_engine import DailyBudget, rank_signals_by_trigger_value
from evolver.swarm import (
    swarm_hook_event,
    swarm_propose,
    swarm_solidify,
    swarm_tick,
)


def _init_git_workspace(ws: Path) -> None:
    """Initialize a real git repository with a baseline commit."""
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run(["git", "config", "user.email", "test@evolver.local"], cwd=ws, check=True)
    subprocess.run(["git", "config", "user.name", "Evolver Test"], cwd=ws, check=True)
    (ws / ".gitignore").write_text(
        ".evolver/\n.evolver_settings/\n.evomap/\nmemory/\nlogs/\n__pycache__/\n.pytest_cache/\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Part 1: Auto-Triggering End-to-End Suite
# ---------------------------------------------------------------------------


class TestAutoTriggerEndToEnd:
    """Verify the full auto-triggering pipeline from IDE/MCP hooks to WFQ ranking."""

    @pytest.mark.asyncio
    async def test_file_hooks_cli_to_cursor_reminder_and_wfq_signal_ranking(
        self,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _init_git_workspace(temp_workspace)
        app_file = temp_workspace / "service.py"
        app_file.write_text("def handle():\n    return 'ok'\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=temp_workspace, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=temp_workspace, check=True)

        evo_dir = temp_workspace / "memory" / "evolution"
        evo_dir.mkdir(parents=True, exist_ok=True)
        graph_path = evo_dir / "memory_graph.jsonl"

        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
        monkeypatch.setenv("OPENCLAW_WORKSPACE", str(temp_workspace))
        monkeypatch.setenv("EVOLUTION_DIR", str(evo_dir))
        monkeypatch.setenv("MEMORY_GRAPH_PATH", str(graph_path))
        monkeypatch.setenv("EVOLVER_LOGS_DIR", str(temp_workspace / "logs"))
        monkeypatch.setenv("TERM_PROGRAM", "xterm")
        monkeypatch.delenv("CURSOR_TRACE_ID", raising=False)
        monkeypatch.delenv("CURSOR_SESSION_ID", raising=False)
        monkeypatch.delenv("HOOK_HOST", raising=False)

        # 1. Simulate an edit introducing an error log & bottleneck -> run signal_detect.main()
        app_file.write_text(
            "def handle():\n    raise RuntimeError('Error: request timeout bottleneck')\n",
            encoding="utf-8",
        )
        edit_payload = json.dumps(
            {
                "tool_input": {
                    "file_path": str(app_file),
                    "content": "Runtime failure! Error: request timeout and latency bottleneck",
                }
            }
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO(edit_payload))
        stdout_buf = io.StringIO()
        monkeypatch.setattr(sys, "stdout", stdout_buf)
        signal_detect.main()

        sig_out = json.loads(stdout_buf.getvalue())
        assert "additional_context" in sig_out
        assert "log_error" in sig_out["additional_context"]
        assert "perf_bottleneck" in sig_out["additional_context"]

        # 2. Run session_end.main() with transcript cwd -> verify stdout JSON, memory graph & cursor
        session_payload = json.dumps(
            {"type": "session_meta", "payload": {"cwd": str(temp_workspace)}}
        )
        monkeypatch.setattr(sys, "stdin", io.StringIO(session_payload))
        se_stdout = io.StringIO()
        monkeypatch.setattr(sys, "stdout", se_stdout)
        session_end.main()

        se_out = json.loads(se_stdout.getvalue())
        assert "systemMessage" in se_out
        assert "[Evolution] Session outcome recorded to local memory" in se_out["systemMessage"]
        assert graph_path.exists()

        # Verify cursor trajectory was incremented by session_end
        rem1 = cursor.reminder(min_trajectories=2)
        assert rem1["trajectories_seen_since"] == 1
        assert rem1["by_trajectory"] is False

        # 3. Fire a second session_end via MCP swarm_hook_event -> reminder becomes due!
        hook_res = swarm_hook_event(
            event="session_end",
            payload={"content": "Test failed: assertion error in handle()"},
            source="e2e-test",
        )
        assert hook_res["ok"] is True
        assert hook_res.get("trajectory_recorded") is True
        assert "test_failure" in hook_res["detected_signals"]

        rem2 = cursor.reminder(min_trajectories=2)
        assert rem2["trajectories_seen_since"] == 2
        assert rem2["by_trajectory"] is True
        assert rem2["due"] is True

        # 4. Run signals_phase -> pending signals from hooks are consumed and ranked via WFQ
        save_genes(
            [
                {
                    "type": "Gene",
                    "id": "gene_error_repair",
                    "category": "repair",
                    "signals_match": ["log_error", "test_failure"],
                    "strategy": ["Fix runtime errors and failing assertions"],
                }
            ]
        )
        ctx: dict[str, Any] = {
            "memory_snippet": "",
            "user_snippet": "",
            "session_log": "",
            "recent_master_log": "",
            "recent_events": [],
        }
        await signals_phase(ctx)
        assert "log_error" in ctx["signals"]
        assert "test_failure" in ctx["signals"]
        assert "perf_bottleneck" in ctx["signals"]

        ranking = ctx.get("trigger_priorities")
        assert isinstance(ranking, dict)
        assert ranking["top_signal"] in ("log_error", "test_failure")
        # Strategic fit with gene_error_repair boosts log_error above unclassified signals
        assert ranking["values"]["log_error"] > ranking["values"]["perf_bottleneck"]

    def test_wfq_anti_starvation_boosts_waiting_signal(self) -> None:
        ranked = rank_signals_by_trigger_value(
            ["user_improvement_suggestion", "log_error"],
            genes=[
                {
                    "id": "g_err",
                    "signals_match": ["log_error"],
                }
            ],
            # user_improvement_suggestion waited 30m (1800s), earning log2(31) -> capped 4.0 boost
            wait_seconds_by_signal={"user_improvement_suggestion": 1800.0, "log_error": 0.0},
            now=2000.0,
        )
        assert ranked["ordered_signals"][0] == "user_improvement_suggestion"
        assert (
            ranked["priorities"]["user_improvement_suggestion"] > ranked["priorities"]["log_error"]
        )

    @pytest.mark.asyncio
    async def test_daily_budget_env_caps_and_guard_enforcement(
        self,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        evo_dir = temp_workspace / "memory" / "evolution"
        evo_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("EVOLUTION_DIR", str(evo_dir))
        monkeypatch.setenv("EVOLVER_TRIGGER_MAX_CYCLES_PER_DAY", "2")
        monkeypatch.setenv("EVOLVER_TRIGGER_PER_PATTERN_CAP", "1")

        budget = DailyBudget()
        assert budget.max_cycles == 2
        assert budget.per_pattern_cap == 1

        # Cycle 1 allowed (run_preflight_checks consumes 1 cycle)
        guard1 = await run_preflight_checks()
        assert guard1.abort is False

        # Per-pattern cap check on a second instance
        budget_p = DailyBudget()
        assert budget_p.snapshot()["cycles"] == 1
        budget_p.consume(pattern="errsig:timeout")
        assert not budget_p.can_fire(pattern="errsig:timeout")
        assert not budget_p.can_fire()

        # Guard now aborts automatically due to daily budget exhausted
        guard2 = await run_preflight_checks()
        assert guard2.abort is True
        assert "daily budget exhausted" in (guard2.reason or "")

    @pytest.mark.asyncio
    async def test_idle_scheduler_throttles_signal_only_and_allows_deep(
        self,
        temp_workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        evo_dir = temp_workspace / "memory" / "evolution"
        evo_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("EVOLUTION_DIR", str(evo_dir))
        save_genes(
            [
                {
                    "type": "Gene",
                    "id": "gene_repair_basic",
                    "category": "repair",
                    "signals_match": ["log_error"],
                    "strategy": ["Fix error"],
                }
            ]
        )

        # 1. Under IDLE_OVERRIDE=signal_only, signals_phase records signal_only
        #    and dispatch_phase skips prompt generation cleanly.
        monkeypatch.setenv("IDLE_OVERRIDE", "signal_only")
        ctx_throttled: dict[str, Any] = {
            "run_id": "run_sig_only",
            "cycle_id": "0001",
            "memory_snippet": "Error: something failed",
            "user_snippet": "",
            "session_log": "",
            "recent_master_log": "",
        }
        await signals_phase(ctx_throttled)
        assert ctx_throttled.get("evolution_intensity") == "signal_only"
        await select_phase(ctx_throttled)
        await dispatch_phase(ctx_throttled)
        assert ctx_throttled.get("skip_mutation_signal_only") is True
        assert "dispatch_prompt" not in ctx_throttled

        # 2. Under IDLE_OVERRIDE=deep, full mutation prompt is dispatched.
        monkeypatch.setenv("IDLE_OVERRIDE", "deep")
        ctx_deep: dict[str, Any] = {
            "run_id": "run_deep",
            "cycle_id": "0002",
            "memory_snippet": "Error: something failed",
            "user_snippet": "",
            "session_log": "",
            "recent_master_log": "",
        }
        await signals_phase(ctx_deep)
        assert ctx_deep.get("evolution_intensity") == "deep"
        await select_phase(ctx_deep)
        await dispatch_phase(ctx_deep)
        assert not ctx_deep.get("skip_mutation_signal_only")
        assert isinstance(ctx_deep.get("dispatch_prompt"), str)
        assert len(ctx_deep["dispatch_prompt"]) > 100


# ---------------------------------------------------------------------------
# Part 2: Real, Reliable & Beneficial Auto-Evolution E2E (Closed Loop)
# ---------------------------------------------------------------------------


class TestAutoEvolutionRealReliableBeneficialE2E:
    """Prove that auto-evolution rolls back harmful edits, learns from hurt attribution,
    pivots to a safe repair gene, and solidifies a verified beneficial fix."""

    @pytest.mark.asyncio
    async def test_two_round_closed_loop_rollback_then_beneficial_repair(
        self,
        temp_workspace: Path,
        armed_pack: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _ = armed_pack
        _init_git_workspace(temp_workspace)
        monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
        monkeypatch.setenv("OPENCLAW_WORKSPACE", str(temp_workspace))
        monkeypatch.setenv("EVOLVER_FF_ENABLE_EVAL_WORKTREE", "0")
        monkeypatch.setenv("EVOLVER_FF_ENABLE_LLM_REVIEW", "0")
        monkeypatch.setattr(
            "evolver.gep.solidify.get_fitness_cascade_commands",
            lambda *a, **kw: [
                {
                    "command": [sys.executable, "-m", "pytest", "test_calc.py", "-q"],
                    "timeout_ms": 30000,
                }
            ],
        )

        # 1. Create a real Python module with a boundary defect and a pytest test file.
        pkg_dir = temp_workspace / "discount_pkg"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
        target_file = pkg_dir / "calc.py"
        original_buggy_code = (
            "def apply_discount(price: float, rate: float) -> float:\n"
            "    if price < 0:\n"
            "        raise ValueError('negative price')\n"
            "    # Bug: does not clamp rate to [0.0, 1.0]\n"
            "    return round(price * (1.0 - rate), 2)\n"
        )
        target_file.write_text(original_buggy_code, encoding="utf-8")

        test_file = temp_workspace / "test_calc.py"
        test_file.write_text(
            "import pytest\n"
            "from discount_pkg.calc import apply_discount\n\n"
            "def test_standard_discount() -> None:\n"
            "    assert apply_discount(100.0, 0.2) == 80.0\n\n"
            "def test_rate_clamped_to_valid_bounds() -> None:\n"
            "    assert apply_discount(100.0, 1.5) == 0.0\n"
            "    assert apply_discount(100.0, -0.5) == 100.0\n",
            encoding="utf-8",
        )

        # Commit baseline so git workspace is clean before Round 1
        subprocess.run(["git", "add", "."], cwd=temp_workspace, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "baseline with boundary bug"],
            cwd=temp_workspace,
            check=True,
        )

        # Seed two genes:
        # - gene_risky_opt: matches all 5 signals -> selected in Round 1 and fails
        # - gene_safe_repair: matches 4 signals -> selected in Round 2 after cooldown
        validation_cmd = "python -m pytest test_calc.py -q"
        save_genes(
            [
                {
                    "type": "Gene",
                    "id": "gene_risky_opt",
                    "category": "repair",
                    "signals_match": [
                        "perf_bottleneck",
                        "capability_gap",
                        "log_error",
                        "deployment_issue",
                        "test_failure",
                        "user_feature_request",
                    ],
                    "strategy": ["Attempt quick arithmetic tweak"],
                    "validation": [validation_cmd],
                },
                {
                    "type": "Gene",
                    "id": "gene_safe_repair",
                    "category": "repair",
                    "signals_match": [
                        "perf_bottleneck",
                        "capability_gap",
                        "log_error",
                        "deployment_issue",
                        "test_failure",
                        "repair_loop",
                        "autopoiesis:repair_loop_guard",
                    ],
                    "strategy": ["Clamp discount rate to [0.0, 1.0] preserving invariants"],
                    "validation": [validation_cmd],
                },
            ]
        )

        # Inject signals from a hook event to trigger Round 1
        rich_failure_text = (
            "Test failed: assertion error in test_rate_clamped_to_valid_bounds! "
            "Error: request timeout latency bottleneck, deploy failed, "
            "feature not supported, please add bounds check."
        )
        swarm_hook_event(
            event="signal_detect",
            payload={
                "file_path": "discount_pkg/calc.py",
                "content": rich_failure_text,
            },
        )

        # =====================================================================
        # ROUND 1: Harmful mutation -> Validation Failure -> Atomic Git Rollback
        # =====================================================================
        tick1 = await swarm_tick()
        assert tick1["ok"] is True
        selected_round1 = tick1["selected_gene"]["id"]
        assert selected_round1 == "gene_risky_opt"

        # Apply a HARMFUL edit that breaks even standard discount
        target_file.write_text(
            "def apply_discount(price: float, rate: float) -> float:\n"
            "    return -999.0  # broken mutation\n",
            encoding="utf-8",
        )

        hyp1 = {
            "hypothesis": "Try constant return value",
            "dimension": "content",
            "mechanism_family": "prompt_edit",
            "target_hook": "discount_pkg/calc.py::apply_discount",
            "mechanism_check": [
                {
                    "id": "fixture-train-1",
                    "before": "rate > 1 returns negative price",
                    "after": "returns clamped price",
                }
            ],
            "expected_outcome": {
                "expected_checks_to_pass": ["pytest"],
            },
        }
        sol1 = swarm_solidify(hypothesis=hyp1)
        assert sol1["ok"] is False
        assert sol1["error"] == "validation_failed"

        # Verify workspace was atomically rolled back to the baseline code!
        assert target_file.read_text(encoding="utf-8") == original_buggy_code

        # Verify EpisodeRecord 1 captured 'hurt' attribution and surprise delta
        ep_list_1 = episode_record.list_episodes()
        assert len(ep_list_1) == 1
        ep1_body = episode_record.load_episode(ep_list_1[0]["id"])
        assert ep1_body is not None
        assert ep1_body["outcome"]["status"] == "failed"
        ep1_attr = episode_record.attach_component_attribution(ep1_body)["gates"]["attribution"]
        assert ep1_attr["status"] == "hurt"
        assert ep1_body["gates"]["prediction_delta"]["matched"] is False
        assert ep1_body["gates"]["prediction_delta"]["unmet_expectations"] == ["pytest"]

        # =====================================================================
        # ROUND 2: Adaptive Pivot -> Cool Down Hurt Gene -> Beneficial Fix
        # =====================================================================
        swarm_hook_event(
            event="signal_detect",
            payload={
                "file_path": "discount_pkg/calc.py",
                "content": rich_failure_text,
            },
        )
        tick2 = await swarm_tick()
        assert tick2["ok"] is True
        # Because Round 1 gene had attribution='hurt', Round 2 cools it down
        # and selects gene_safe_repair!
        selected_round2 = tick2["selected_gene"]["id"]
        assert selected_round2 == "gene_safe_repair"
        # Verify the dispatch prompt warns the agent about Round 1's hurt attribution
        assert "status=hurt" in tick2["dispatch_prompt"]

        # Submit a clean, beneficial fix via structured GeneProposal (with INV x DOM tags)
        beneficial_code = (
            "def apply_discount(price: float, rate: float) -> float:\n"
            "    if price < 0:\n"
            "        raise ValueError('negative price')\n"
            "    clamped = min(max(rate, 0.0), 1.0)\n"
            "    return round(price * (1.0 - clamped), 2)\n"
        )
        proposal = {
            "action": "patch",
            "gene_id": selected_round2,
            "note": (
                "[INV-01] [DOM-01] Clamp discount rate to [0.0, 1.0] "
                "before computing discounted price"
            ),
            "edits": [
                {
                    "op": "replace",
                    "file": "discount_pkg/calc.py",
                    "target": (
                        "    # Bug: does not clamp rate to [0.0, 1.0]\n"
                        "    return round(price * (1.0 - rate), 2)\n"
                    ),
                    "content": (
                        "    clamped = min(max(rate, 0.0), 1.0)\n"
                        "    return round(price * (1.0 - clamped), 2)\n"
                    ),
                }
            ],
        }
        hyp2 = {
            "hypothesis": (
                "Clamp rate to [0.0, 1.0] so out-of-range rates "
                "do not produce negative or inflated prices"
            ),
            "dimension": "content",
            "mechanism_family": "prompt_edit",
            "target_hook": "discount_pkg/calc.py::apply_discount",
            "mechanism_check": [
                {
                    "id": "fixture-train-1",
                    "before": "rate=1.5 returned -50.0 and rate=-0.5 returned 150.0",
                    "after": (
                        "rate=1.5 clamps to 1.0 (returns 0.0) "
                        "and rate=-0.5 clamps to 0.0 (returns 100.0)"
                    ),
                }
            ],
            "expected_outcome": {
                "expected_checks_to_pass": ["pytest"],
            },
        }

        prop_res = swarm_propose(proposal=proposal, hypothesis=hyp2)
        assert prop_res["ok"] is True
        assert "discount_pkg/calc.py" in prop_res["files_changed"]
        assert target_file.read_text(encoding="utf-8") == beneficial_code

        sol2 = swarm_solidify()
        assert sol2["ok"] is True, f"Expected solidify to succeed, got: {sol2}"

        # Verify EpisodeRecord 2 captured 'helped' attribution, matched prediction, and contrast
        ep_list_2 = episode_record.list_episodes()
        assert len(ep_list_2) == 2
        ep2_body = episode_record.load_episode(ep_list_2[1]["id"])
        assert ep2_body is not None
        assert ep2_body["outcome"]["status"] == "success"
        ep2_attr = episode_record.attach_component_attribution(ep2_body)["gates"]["attribution"]
        assert ep2_attr["status"] == "helped"
        assert ep2_body["gates"]["prediction_delta"]["matched"] is True
        assert ep2_body["gates"]["prediction_delta"]["unmet_expectations"] == []

        contrast = episode_record.compute_behavioral_contrast(
            ep2_body.get("checks") or [],
            ep1_body.get("checks") or [],
            diff_text=str(ep2_body.get("diff") or ""),
        )
        assert len(contrast["check_transitions"]["newly_passed"]) == 1
        assert contrast["check_transitions"]["regressed"] == []

        # Verify the fixed code is committed in git and passes pytest directly
        pytest_run = subprocess.run(
            [sys.executable, "-m", "pytest", "test_calc.py", "-q"],
            cwd=temp_workspace,
            capture_output=True,
            text=True,
            check=False,
        )
        assert pytest_run.returncode == 0
        assert target_file.read_text(encoding="utf-8") == beneficial_code

        # Verify the beneficial fix was atomically committed into git history with score=1.0
        assert sol2.get("score") == 1.0
        git_log = subprocess.run(
            ["git", "log", "-1", "--oneline"],
            cwd=temp_workspace,
            capture_output=True,
            text=True,
            check=True,
        )
        assert selected_round2 in git_log.stdout
