"""Strategist Tier 3 tests: S-5 Pareto, S-6 direction & seal, S-8a routing, P3-1/P3-2 capsule."""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path
from typing import Any

import pytest

from evolver import swarm
from evolver.bench.compare import compare_paired_pareto
from evolver.bench.frozen_gate import direction_envelope_for_host
from evolver.experiment import agent_runner
from evolver.experiment import cli as exp_cli
from evolver.experiment.comparison import run_comparison
from evolver.experiment.time_capsule import (
    build_builtin_time_capsule,
    evaluate_task_patch_with_pytest,
    install_time_capsule,
    run_time_capsule_paired_eval,
)
from evolver.gep import val_seal
from evolver.gep.router import compute_routing_advice
from evolver.proxy.router.model_router import resolve_model


def _make_rows(
    n: int,
    *,
    passes: list[bool],
    costs: list[float],
    slices: list[str] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(n):
        sl = slices[i] if slices is not None else ("internal" if i % 2 == 0 else "external")
        rows.append(
            {
                "id": f"t_{i:02d}",
                "slice": sl,
                "passed": passes[i],
                "score": 1.0 if passes[i] else 0.0,
                "cost": costs[i],
            }
        )
    return rows


class TestS5DualRouteParetoEngine:
    def test_route_a_quality_win_and_route_b_efficiency_win_and_keep_baseline(self) -> None:
        n = 32
        # Route A: McNemar p < 0.01 + external net wins > 0 + cost <= 1.05
        pass_b = [False] * 14 + [True] * 18
        pass_a = [True] * 12 + [False] * 2 + [True] * 18
        res_a = compare_paired_pareto(
            {"per_task": _make_rows(n, passes=pass_a, costs=[103.0] * n)},
            {"per_task": _make_rows(n, passes=pass_b, costs=[100.0] * n)},
            alpha=0.01,
        )
        assert res_a["p_mcnemar"] < 0.01
        assert res_a["external_net_wins"] > 0
        assert res_a["verdict"] == "quality_win"

        # Cost cap guard: +10% (> 1.05 default) stays keep_baseline under default cap
        res_over_cap = compare_paired_pareto(
            {"per_task": _make_rows(n, passes=pass_a, costs=[110.0] * n)},
            {"per_task": _make_rows(n, passes=pass_b, costs=[100.0] * n)},
            alpha=0.01,
        )
        assert res_over_cap["verdict"] == "keep_baseline"

        # Route B: flat accuracy (d == 0.0) + clear cost reduction (rho + SE <= 0.85)
        res_eff = compare_paired_pareto(
            {"per_task": _make_rows(n, passes=pass_b, costs=[60.0] * n)},
            {"per_task": _make_rows(n, passes=pass_b, costs=[100.0] * n)},
            alpha=0.01,
        )
        assert res_eff["d"] == 0.0
        assert res_eff["rho_upper_ci"] <= 0.85
        assert res_eff["verdict"] == "efficiency_win"

        # keep_baseline when cheaper but accuracy drops
        pass_drop = [False] * 18 + [True] * 14
        res_drop = compare_paired_pareto(
            {"per_task": _make_rows(n, passes=pass_drop, costs=[40.0] * n)},
            {"per_task": _make_rows(n, passes=pass_b, costs=[100.0] * n)},
            alpha=0.01,
        )
        assert res_drop["d"] < 0
        assert res_drop["verdict"] == "keep_baseline"

    def test_boolq_32x_small_denominator_outlier_stability(self) -> None:
        # 31 tasks equal (cost 100.0 vs 100.0) + 1 small-denominator outlier (32.0 vs 1.0 = 32x)
        costs_a = [100.0] * 31 + [32.0]
        costs_b = [100.0] * 31 + [1.0]
        passes = [True] * 32
        res = compare_paired_pareto(
            {"per_task": _make_rows(32, passes=passes, costs=costs_a)},
            {"per_task": _make_rows(32, passes=passes, costs=costs_b)},
        )
        # Naive arithmetic mean of per-task ratios would be (31*1 + 32)/32 = 1.969;
        # ratio-of-means and geometric mean remain bounded.
        assert res["rho"] < 1.05
        assert res["rho_geometric"] < 1.15

    def test_run_comparison_exposes_pareto_summary(self) -> None:
        tasks = [
            {
                "id": f"task_{i}",
                "slice": "internal" if i == 0 else "external",
                "prompt": f"Solve python task {i}",
                "signals": ["python", "fix"],
                "baseline_pass": i % 2 == 0,
                "evolved_pass": True,
                "baseline_cost": 1.0,
                "evolved_cost": 0.5,
            }
            for i in range(6)
        ]
        res = run_comparison(
            tasks,
            genes=[
                {
                    "id": "g_cheap",
                    "signals_match": ["fix"],
                    "routing_hint": {"tier": "cheap", "reasoning_level": "low"},
                }
            ],
            agent_fn=lambda _prompt, ctx: ("ok", 50 if ctx else 100),
        )
        assert "pareto" in res
        assert res["pareto"]["rho"] < 1.0


class TestS6DirectionFeedbackAndSeal:
    def test_direction_envelope_and_swarm_mask_raw_floats(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = direction_envelope_for_host(
            {
                "armed": True,
                "score": 0.8125,
                "baseline": 0.75,
                "verdict": "accept",
                "reason": "strict_improvement",
                "accept": True,
                "soft_accept": False,
            },
            duration_ms=700,
            baseline_duration_ms=1000,
        )
        assert env["val_direction"] == "improved"
        assert env["cost_direction"] == "lower"
        for forbidden in ("score", "baseline", "delta", "rho"):
            assert forbidden not in env

        payload: dict[str, Any] = {
            "ok": True,
            "bench_pack": {
                "armed": True,
                "score": 0.91,
                "baseline": 0.80,
                "delta": 0.11,
                "per_task": [{"id": "t1", "score": 1.0}],
                "rounds": [{"score": 0.91}],
                "verdict": "accept",
                "reason": "strict_improvement",
                "accept": True,
                "next_steps": ["keep iterating"],
                "warnings": ["advisory only"],
            },
        }
        swarm._attach_host_direction(payload)
        bp = payload["bench_pack"]
        assert bp["val_direction"] == "improved"
        assert payload["gate_direction"]["val_direction"] == "improved"
        assert bp["next_steps"] == ["keep iterating"]
        assert bp["warnings"] == ["advisory only"]
        for secret_k in ("score", "baseline", "delta", "per_task", "rounds"):
            assert secret_k not in bp

        # Fail-closed when direction_envelope_for_host raises
        monkeypatch.setattr(
            "evolver.bench.frozen_gate.direction_envelope_for_host",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        fail_payload: dict[str, Any] = {
            "ok": True,
            "bench_pack": {
                "armed": True,
                "score": 0.91,
                "baseline": 0.80,
                "delta": 0.11,
                "per_task": [{"id": "t1", "score": 1.0}],
                "verdict": "accept",
            },
        }
        swarm._attach_host_direction(fail_payload)
        fbp = fail_payload["bench_pack"]
        assert fbp["val_direction"] == "unmeasured"
        assert "score" not in fbp and "per_task" not in fbp

    def test_val_seal_seals_time_capsule_hidden_and_test_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evomap-home"))
        receipt = install_time_capsule(force=True)
        assert receipt["ok"] is True

        pack = build_builtin_time_capsule()
        dev_task = next(t for t in pack["tasks"] if t["split"] == "dev_feedback")
        hidden_task = next(t for t in pack["tasks"] if t["split"] == "hidden_select")
        sealed_task = next(t for t in pack["tasks"] if t["split"] == "sealed_test")

        # dev_feedback stays public; hidden_select and sealed_test titles are sealed
        assert val_seal.scan(dev_task["title"]) == []
        assert val_seal.scan(hidden_task["title"])
        assert val_seal.scan(sealed_task["title"])
        with pytest.raises(val_seal.ValSealBreachError, match="val seal breached"):
            val_seal.assert_sealed(sealed_task["title"], where="prompt")


class TestS8aRoutingHint:
    def test_routing_advice_escalation_and_model_router_and_agent_runner(self) -> None:
        adv1 = compute_routing_advice(
            {"id": "op_cheap", "routing_hint": {"tier": "cheap", "reasoning_level": "low"}},
            consecutive_failures=1,
        )
        assert adv1["tier"] == "cheap"
        assert adv1["reasoning_level"] == "low"
        assert adv1["escalated"] is False

        adv2 = compute_routing_advice(
            {"id": "op_cheap", "routing_hint": {"tier": "cheap", "reasoning_level": "low"}},
            consecutive_failures=2,
        )
        assert adv2["tier"] == "mid"
        assert adv2["reasoning_level"] == "medium"
        assert adv2["escalated"] is True

        resolved = resolve_model(routing_hint={"tier": "cheap", "reasoning_level": "low"})
        assert resolved["tier"] == "cheap"
        assert resolved["reasoning_level"] == "low"

        task_res = agent_runner.run_task(
            {
                "id": "t_r",
                "prompt": "Fix",
                "signals": ["fix"],
                "baseline_pass": False,
                "evolved_pass": True,
                "tokens_used": 100,
            },
            genes=[
                {
                    "id": "g_cheap",
                    "signals_match": ["fix"],
                    "routing_hint": {"tier": "cheap", "reasoning_level": "low"},
                }
            ],
            agent_fn=lambda _prompt, _ctx: ("fixed", 100),
        )
        assert task_res.routing_tier == "cheap"
        assert task_res.weighted_cost == 100.0


class TestP31P32TimeCapsuleAndCLIV2:
    def test_builtin_capsule_counts_and_every_task_red_then_green_pytest(self) -> None:
        pack = build_builtin_time_capsule()
        tasks = pack["tasks"]
        sealed = [t for t in tasks if t["split"] == "sealed_test"]
        internals = [t for t in sealed if t["slice"] == "internal"]
        externals = [t for t in sealed if t["slice"] == "external"]
        dev = [t for t in tasks if t["split"] == "dev_feedback"]
        hidden = [t for t in tasks if t["split"] == "hidden_select"]

        assert len(sealed) >= 32
        assert len(internals) == 16
        assert len(externals) == 16
        assert len(dev) >= 2
        assert len(hidden) >= 2
        for ext in externals:
            assert ext["provenance"].get("repo")
            assert ext["provenance"].get("license")

        def _check_one(task: dict[str, Any]) -> tuple[str, bool, bool]:
            red = evaluate_task_patch_with_pytest(task, task["buggy_files"])
            green = evaluate_task_patch_with_pytest(task, task["reference_fix_files"])
            return str(task["id"]), bool(red["passed"]), bool(green["passed"])

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(_check_one, tasks))

        for tid, red_pass, green_pass in results:
            assert red_pass is False, f"{tid} buggy_files unexpectedly passed pytest"
            assert green_pass is True, f"{tid} reference_fix_files failed pytest"

    def test_cli_install_and_stage_exit_v2_end_to_end(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evomap-home"))
        monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / ".evolver" / "gep"))

        capsule_file = tmp_path / "capsule_v2.json"
        install_out = tmp_path / "install_receipt.json"
        rc_install = exp_cli.main(
            [
                "--install-time-capsule",
                "--capsule-path",
                str(capsule_file),
                "--output",
                str(install_out),
            ]
        )
        assert rc_install == 0
        receipt = json.loads(install_out.read_text(encoding="utf-8"))
        assert receipt["ok"] is True
        assert receipt["sealed_test_count"] == 32
        assert receipt["internal_count"] == 16
        assert receipt["external_count"] == 16

        report_file = tmp_path / "stage_exit_v2_report.json"
        per_task_file = tmp_path / "per_task_results.jsonl"

        # Without --allow-stub, stub smoke run must NOT pass gate (exit 2, stage_exit_passed=False)
        rc_v2_blocked = exp_cli.main(
            [
                "--stage-exit-v2",
                "--capsule-path",
                str(capsule_file),
                "--order-seed",
                "7",
                "--output",
                str(report_file),
                "--per-task-output",
                str(per_task_file),
            ]
        )
        assert rc_v2_blocked == 2
        blocked_report = json.loads(report_file.read_text(encoding="utf-8"))
        assert blocked_report["agent_mode"] == "stub"
        assert blocked_report["harness_smoke_ok"] is True
        assert blocked_report["stage_exit_passed"] is False

        # With --allow-stub, offline smoke exits 0 while still marking stage_exit_passed=False
        rc_v2 = exp_cli.main(
            [
                "--stage-exit-v2",
                "--allow-stub",
                "--capsule-path",
                str(capsule_file),
                "--order-seed",
                "7",
                "--output",
                str(report_file),
                "--per-task-output",
                str(per_task_file),
            ]
        )
        assert rc_v2 == 0
        report = json.loads(report_file.read_text(encoding="utf-8"))
        assert report["schema_version"] == "stage_exit_v2.report.v1"
        assert report["agent_mode"] == "stub"
        assert report["n_tasks"] == 32
        assert report["order_seed"] == 7
        assert report["harness_smoke_ok"] is True
        assert report["stage_exit_passed"] is False
        assert report["verdict"] == "quality_win"
        assert report["pareto_latency"]["external_net_wins"] > 0

        # Custom agent receives blind view ONLY (zero reference_fix_files or test_files leaked)
        pack = build_builtin_time_capsule()
        private_refs = {
            str(t["id"]): dict(t["reference_fix_files"])
            for t in pack["tasks"]
            if t["split"] == "sealed_test"
        }
        leaked_keys: list[set[str]] = []

        def blind_custom_agent(task_view: dict[str, Any], ctx: str, _root: Path) -> dict[str, Any]:
            leaked_keys.append(set(task_view.keys()) & {"reference_fix_files", "test_files"})
            if "[Operator" in ctx or "Operator Cards" in ctx:
                return {
                    "files": private_refs[str(task_view["id"])],
                    "tokens": 600,
                    "tier": "cheap",
                    "triage_ms": 120,
                }
            return {
                "files": dict(task_view["buggy_files"]),
                "tokens": 1800,
                "tier": "mid",
                "triage_ms": 950,
            }

        custom_report = run_time_capsule_paired_eval(
            capsule_path=capsule_file,
            patch_agent_fn=blind_custom_agent,
            order_seed=7,
        )
        assert all(not ks for ks in leaked_keys)
        assert custom_report["agent_mode"] == "custom"
        assert custom_report["stage_exit_passed"] is True

        lines = [ln for ln in per_task_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 32
        parsed = [json.loads(ln) for ln in lines]
        assert sum(1 for row in parsed if row["slice"] == "external") == 16
        assert all(row["order"] in ("AB", "BA") for row in parsed)

        # Ensure standard CLI without --tasks and without v2 flags still exits with code 2
        with pytest.raises(SystemExit) as exc_info:
            exp_cli.main([])
        assert exc_info.value.code == 2
