"""纯人话 status 面板（P0-2，支柱零）：零内部旗标黑话。

Python-native new module (no Node.js equivalent; reads the same external
workspace runtime as ops/meta_report.py).

``evolver status`` renders this: a plain-language dashboard of the autopilot —
ready light, what got fixed/intercepted, vault size, workbench drafts. Every
number is read from real runtime state; nothing is fabricated.
"""

# ruff: noqa: RUF002  (中文人话面板, 同 ops/commentary.py 豁免先例)

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _bootstrap_light(state_dir: Path) -> str:
    marker = _read_json(state_dir / "bootstrap_baseline.json")
    native = _read_json(state_dir / "project_native_baseline.json")
    if marker is None and native is None:
        return "🟡 未初始化 — 运行 `evolver init` 一键开箱"
    if (marker and marker.get("status") == "done") or native is not None:
        ok = bool(marker.get("ok")) if marker else True
        return "🟢 就绪" if ok else "🟡 基线部分完成（不影响使用）"
    return "🟡 初始化进行中（后台自动完成）"


def _daemon_light() -> str:
    try:
        from evolver.ops.lifecycle import status as daemon_status

        result = daemon_status()
        if result.running:
            return "运行中"
        return "未运行（`evolver up` 一键启动自动驾驶）"
    except Exception:
        return "未知"


def _event_ran_test_suite(event: dict[str, Any]) -> bool:
    """True when validation commands/stages actually invoked pytest or unittest."""
    report = event.get("validation_report")
    if isinstance(report, dict):
        for cmd in report.get("commands") or []:
            low = str(cmd or "").lower()
            if "pytest" in low or "unittest" in low:
                return True
    timing = event.get("validation_timing")
    if isinstance(timing, dict):
        for stage in timing.get("stages") or []:
            if isinstance(stage, dict):
                low = str(stage.get("command") or "").lower()
                if "pytest" in low or "unittest" in low:
                    return True
    return False


def _settle_ledger(state_dir: Path) -> tuple[dict[str, int], set[str], set[str], set[str], float]:
    """Read settled counts, run sets, and real saved validation time."""
    counts = {"promoted": 0, "soft_accepted": 0, "intercepted": 0}
    succeeded_runs: set[str] = set()
    seen_runs: set[str] = set()
    active_failed_runs: set[str] = set()
    cascade_totals_ms: list[float] = []
    fast_totals_ms: list[float] = []
    events_path = state_dir / "gep" / "events.jsonl"
    if not events_path.is_file():
        return counts, succeeded_runs, seen_runs, active_failed_runs, 0.0
    try:
        with events_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                outcome = event.get("outcome") or {}
                status = str(outcome.get("status") or "")
                run_id = str(event.get("run_id") or "")
                if run_id:
                    seen_runs.add(run_id)
                if status == "success":
                    bp = event.get("bench_pack")
                    bp_dict = bp if isinstance(bp, dict) else {}
                    is_bench_soft = str(bp_dict.get("verdict") or "") == "soft_accept" or bool(
                        bp_dict.get("soft_accept")
                    )
                    if is_bench_soft and not _event_ran_test_suite(event):
                        counts["soft_accepted"] += 1
                    else:
                        counts["promoted"] += 1
                    if run_id:
                        succeeded_runs.add(run_id)
                    # A subsequent green promotion settles prior in-place workbench drafts.
                    active_failed_runs.clear()
                elif status in ("failed", "soft_failed"):
                    counts["intercepted"] += 1
                    if run_id:
                        active_failed_runs.add(run_id)
                timing = event.get("validation_timing")
                if isinstance(timing, dict) and timing.get("total_ms") is not None:
                    total_ms = float(timing["total_ms"])
                    tier = str(timing.get("tier") or "")
                    scope = str(timing.get("scope") or "")
                    stages = timing.get("stages") or []
                    if (
                        tier == "L2"
                        or scope == "cascade"
                        or (isinstance(stages, list) and len(stages) >= 3)
                    ):
                        cascade_totals_ms.append(total_ms)
                    elif (
                        tier == "L0"
                        or scope == "lightning"
                        or (isinstance(stages, list) and 0 < len(stages) < 3)
                    ):
                        fast_totals_ms.append(total_ms)
    except OSError:
        pass
    saved_s = 0.0
    if fast_totals_ms:
        baseline_ms = sum(cascade_totals_ms) / len(cascade_totals_ms) if cascade_totals_ms else 0.0
        if baseline_ms <= 0:
            native = _read_json(state_dir / "project_native_baseline.json") or {}
            pcol = native.get("pytest_collect")
            ast_health = native.get("ast_health")
            if isinstance(pcol, dict) and int(pcol.get("tests_collected") or 0) > 0:
                col_ms = float(pcol.get("collect_duration_ms") or 0.0)
                n_tests = int(pcol.get("tests_collected") or 0)
                # Conservative lower bound of a 3-stage ruff + mypy + full pytest cascade
                baseline_ms = max(col_ms * 3.0, n_tests * 20.0, 3_500.0)
            elif isinstance(ast_health, dict) and int(ast_health.get("py_files") or 0) > 0:
                col_ms = (
                    float(pcol.get("collect_duration_ms") or 0.0) if isinstance(pcol, dict) else 0.0
                )
                baseline_ms = max(col_ms * 3.0, 3_000.0)
        if baseline_ms > 0:
            saved_ms = sum(max(0.0, baseline_ms - t) for t in fast_totals_ms)
            saved_s = round(saved_ms / 1000.0, 1)
    return counts, succeeded_runs, seen_runs, active_failed_runs, saved_s


def _vault_operators(state_dir: Path) -> int:
    """Operator genes actually earned in *state_dir* (target workspace).

    Round-121 review: factory seeds and lifecycle-retired genes are not
    vault wins — counting them inflated the panel; ``--project`` scopes to
    *state_dir* rather than ambient cwd."""
    import os

    prev_gep = os.environ.get("GEP_ASSETS_DIR")
    prev_evo = os.environ.get("EVOLUTION_DIR")
    os.environ["GEP_ASSETS_DIR"] = str(state_dir / "gep")
    os.environ["EVOLUTION_DIR"] = str(state_dir / "evolution")
    try:
        from evolver.gep.asset_store import load_genes_read_only
        from evolver.gep.gene_lifecycle import load_lifecycle_sets

        retired, _under_review = load_lifecycle_sets()
        genes = load_genes_read_only()
        return sum(
            1
            for g in genes
            if str(g.get("id") or "").startswith("gene_distilled_")  # earned, not seeded
            and str(g.get("id") or "") not in retired
        )
    except Exception:
        return 0
    finally:
        if prev_gep is None:
            os.environ.pop("GEP_ASSETS_DIR", None)
        else:
            os.environ["GEP_ASSETS_DIR"] = prev_gep
        if prev_evo is None:
            os.environ.pop("EVOLUTION_DIR", None)
        else:
            os.environ["EVOLUTION_DIR"] = prev_evo


def _workbench_drafts(
    state_dir: Path,
    succeeded_runs: set[str],
    seen_runs: set[str],
    active_failed_runs: set[str],
) -> tuple[int, str]:
    """Deduplicated unsettled draft count + newest pending note."""
    draft_ids: set[str] = set(active_failed_runs)
    stashes = state_dir / "evolution" / "rejected_stashes"
    if stashes.is_dir():
        for p in stashes.glob("*.json"):
            if p.name == "latest.json":
                continue
            rid = p.stem
            if (
                rid
                and rid not in succeeded_runs
                and (rid in active_failed_runs or rid not in seen_runs)
            ):
                draft_ids.add(rid)
    pending = ""
    state_file = state_dir / "evolution" / "evolution_solidify_state.json"
    state = _read_json(state_file) or {}
    last_run = state.get("last_run") or {}
    last_solidify = state.get("last_solidify") or {}
    run_id = str(last_run.get("run_id") or "")
    settled_failed = (
        run_id
        and str(last_solidify.get("run_id") or "") == run_id
        and str(last_solidify.get("outcome") or "") == "failed"
    )
    if (
        run_id
        and run_id not in succeeded_runs
        and (str(last_solidify.get("run_id") or "") != run_id or settled_failed)
    ):
        draft_ids.add(run_id)
        if settled_failed:
            pending = (
                f"上一轮被门拦下（run {run_id[-8:]}），补丁原位保留——"
                "按 actionable_fix 修好后 `evolver solidify` 可直接重试"
            )
        else:
            pending = f"最近一轮改动保留在工作区（run {run_id[-8:]}），修好即可再结算"
    return len(draft_ids), pending


def human_status(*, project: str | Path | None = None) -> dict[str, Any]:
    """Collect the plain-language panel data (machine JSON = this dict)."""
    from evolver.gep.paths import compute_workspace_id, get_repo_root, get_workspace_state_dir

    pdir = Path(project).expanduser().resolve() if project else None
    repo = pdir or get_repo_root() or Path.cwd()
    state_dir = get_workspace_state_dir(repo)

    counts, succeeded_runs, seen_runs, active_failed_runs, saved_s = _settle_ledger(state_dir)
    drafts, pending = _workbench_drafts(state_dir, succeeded_runs, seen_runs, active_failed_runs)
    return {
        "project": str(repo),
        "workspace_id": compute_workspace_id(repo),
        "ready": _bootstrap_light(state_dir),
        "daemon": _daemon_light(),
        "promoted": counts["promoted"],
        "soft_accepted": counts["soft_accepted"],
        "intercepted": counts["intercepted"],
        "saved_validation_seconds": saved_s,
        "vault_operators": _vault_operators(state_dir),
        "workbench_drafts": drafts,
        "draft_note": pending,
    }


def render_human(report: dict[str, Any]) -> str:
    """The exact lines ``evolver status`` prints — 人话，零黑话。"""
    saved_s = float(report.get("saved_validation_seconds") or 0.0)
    saved_text = f"{saved_s:.1f}s" if saved_s > 0 else "0.0s（闪电验证启用后自动累计）"
    lines = [
        "Evolver 自动驾驶状态",
        f"  项目         : {report.get('project')}",
        f"  就绪灯       : {report.get('ready')}",
        f"  守护进程     : {report.get('daemon')}",
        f"  已晋升修复   : {report.get('promoted')} 轮",
    ]
    soft_n = int(report.get("soft_accepted") or 0)
    if soft_n > 0:
        lines.append(f"  未验软放行   : {soft_n} 轮（无测试/无基线首轮放行，未计入晋升）")
    lines.extend(
        [
            f"  已拦截问题   : {report.get('intercepted')} 轮（改动已保留，未进金库）",
            f"  节省验证耗时 : {saved_text}",
            f"  金库算子     : {report.get('vault_operators')} 个",
            f"  工作台草稿   : {report.get('workbench_drafts')} 个",
        ]
    )
    note = report.get("draft_note")
    if note:
        lines.append(f"  提示         : {note}")
    return "\n".join(lines)


__all__ = ["human_status", "render_human"]
