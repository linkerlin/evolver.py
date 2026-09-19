"""Charter receipt machine verification (演进方案.md §11.4 P1).

Periodically emits version, dogfood round, cumulative gated metrics, drift vs
charter targets, unique env variable count, tracked runtime git cleanliness,
and anchor epoch governance assertions.
"""

from __future__ import annotations

import glob
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from evolver.config import (
    ANCHOR_TRIGGER_SURFACES,
    GATE_SOAK_INTERCEPT_MAX,
    GATE_SOAK_INTERCEPT_MIN,
    GATE_SOAK_MAX_FALSE_KILL,
    GATE_SOAK_MIN_RUNS,
)
from evolver.gep.acceptance.report import gate_soak_recommendation, summarize_acceptance
from evolver.gep.anchor import anchor_dir, load_epoch
from evolver.gep.asset_store import read_all_events
from evolver.gep.git_ops import run_cmd
from evolver.gep.paths import get_repo_root, get_workspace_root
from evolver.ops.soak_env import evolution_dir_inside_repo, read_gate_verifications, soak_root

#: Engine-surface commits may lag the last ledger event by at most this much
#: before the loop is considered bypassed. In the healthy flow the solidify
#: auto-commit lands seconds after its event; drift only GROWS when code
#: lands through direct-engineering sessions (round-30~34: five rounds, ~30h
#: drift, zero events — DEBUG #44). Module constant, not an env knob.
LOOP_STALE_THRESHOLD_S: Final = 3600


def _read_version(repo: Path) -> str:
    pyproject = repo / "pyproject.toml"
    if not pyproject.is_file():
        return "unknown"
    content = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    return match.group(1) if match else "unknown"


def _extract_latest_round(repo: Path, events: list[dict[str, Any]]) -> int:
    """Best-effort extraction of highest dogfood round from git log or events."""
    try:
        log_out = run_cmd(["log", "-n", "50", "--format=%s"], cwd=repo)
        round_match = re.search(r"round-(\d+)", log_out, re.IGNORECASE)
        if round_match:
            return int(round_match.group(1))
    except Exception:
        pass
    for evt in reversed(events):
        comment = str(evt.get("comment", ""))
        round_match = re.search(r"round-(\d+)", comment, re.IGNORECASE)
        if round_match:
            return int(round_match.group(1))
    return len(events)


def count_unique_evolver_envs(repo: Path) -> int:
    """Count distinct EVOLVER_* environment variables referenced across src/."""
    src_dir = repo / "src"
    if not src_dir.is_dir():
        return 0
    env_vars: set[str] = set()
    for py_file in glob.glob(str(src_dir / "**" / "*.py"), recursive=True):
        try:
            content = Path(py_file).read_text(encoding="utf-8")
            env_vars.update(re.findall(r"\bEVOLVER_[A-Z0-9_]+\b", content))
        except OSError:
            continue
    return len(env_vars)


def get_tracked_runtime_files(repo: Path) -> list[str]:
    """Return git-tracked paths under memory/."""
    try:
        out = run_cmd(["ls-files", "memory"], cwd=repo)
        return [line.strip() for line in out.splitlines() if line.strip()]
    except Exception:
        return []


def _parse_ts(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(raw.strip())
    except (ValueError, AttributeError):
        return None


def loop_integrity(
    events: list[dict[str, Any]],
    repo: Path,
) -> dict[str, Any]:
    """Loop-integrity receipt (round-37, DEBUG #44 + RSI §6.6 finding 1).

    The event ledger only records what happened — it is blind to whether the
    loop was running at all. Five bypass rounds (round-30~34) landed engine
    commits with zero events, silently freezing the soak sample and leaving
    integration defects unvalidated. This compares the newest commit touching
    the engine surface (``src/`` / ``tests/``) against the newest ledger
    event: drift beyond :data:`LOOP_STALE_THRESHOLD_S` means code moved
    without the loop. Advisory only — it does not gate promotion and never
    blocks; its job is to make bypass visible to the machine.
    """
    last_event_dt: datetime | None = None
    for evt in events:
        dt = _parse_ts(str(evt.get("timestamp") or ""))
        if dt is not None and (last_event_dt is None or dt > last_event_dt):
            last_event_dt = dt
    try:
        commit_iso = run_cmd(
            ["log", "-1", "--format=%cI", "--", "src", "tests"], cwd=repo
        )
    except Exception:
        commit_iso = ""
    commit_dt = _parse_ts(commit_iso) if commit_iso else None

    receipt: dict[str, Any] = {
        "last_event": last_event_dt.isoformat() if last_event_dt else None,
        "last_engine_commit": commit_dt.isoformat() if commit_dt else None,
        "drift_seconds": None,
        "threshold_seconds": LOOP_STALE_THRESHOLD_S,
    }
    if commit_dt is None:
        receipt["status"] = "no_engine_commits"
    elif last_event_dt is None:
        receipt["status"] = "no_events"
    else:
        drift = (commit_dt - last_event_dt).total_seconds()
        receipt["drift_seconds"] = round(drift)
        receipt["status"] = "ok" if drift <= LOOP_STALE_THRESHOLD_S else "stale"
    return receipt


def build_charter_report(
    *,
    repo: Path | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the complete charter compliance receipt."""
    repo_root = repo or get_repo_root(_quiet=True) or get_workspace_root()
    all_events = events if events is not None else read_all_events()

    version = _read_version(repo_root)
    dogfood_round = _extract_latest_round(repo_root, all_events)

    acc_metrics = summarize_acceptance(all_events, verified=read_gate_verifications())
    recommendation = gate_soak_recommendation(acc_metrics)
    inside_repo = evolution_dir_inside_repo()

    gated_cum = int(acc_metrics.get("gated_cumulative", 0))
    gated_runs = int(acc_metrics.get("gated_runs", 0))
    false_kill = acc_metrics.get("false_kill_risk")
    interception = float(acc_metrics.get("interception_rate", 0.0))
    verified_tp = int(acc_metrics.get("verified_true_positives", 0))
    soak_count = len(all_events)

    cum_met = gated_cum >= GATE_SOAK_MIN_RUNS
    fk_met = (false_kill is not None) and (false_kill <= GATE_SOAK_MAX_FALSE_KILL)
    int_met = GATE_SOAK_INTERCEPT_MIN <= interception <= GATE_SOAK_INTERCEPT_MAX
    soak_outside_met = not inside_repo

    env_count = count_unique_evolver_envs(repo_root)
    tracked_runtime = get_tracked_runtime_files(repo_root)
    runtime_clean = len(tracked_runtime) <= 1 and all(
        "LESSONS_LEARNED.md" in p for p in tracked_runtime
    )
    loop_receipt = loop_integrity(all_events, repo_root)

    epoch_info = load_epoch()
    anchor_installed = epoch_info is not None
    anchor_covers_acceptance = (
        "src/evolver/gep/acceptance/" in ANCHOR_TRIGGER_SURFACES
        and "tests/gep/acceptance/" in ANCHOR_TRIGGER_SURFACES
    )
    anchor_covers_ingress = "src/evolver/gep/llm_template.py" in ANCHOR_TRIGGER_SURFACES

    # Charter status synthesis
    verdict = recommendation.get("verdict", "unknown")
    ready_for_promotion = (
        verdict == "ready"
        and cum_met
        and fk_met
        and int_met
        and soak_outside_met
        and runtime_clean
        and anchor_installed
        and anchor_covers_acceptance
        and anchor_covers_ingress
    )

    return {
        "version": version,
        "round": dogfood_round,
        "acceptance": {
            "gated_cumulative": gated_cum,
            "gated_runs": gated_runs,
            "verdict": verdict,
            "recommendation": recommendation.get("recommendation", ""),
            "interception_rate": interception,
            "false_kill_risk": false_kill,
            "verified_true_positives": verified_tp,
            "criteria_met": {
                "cumulative_sufficient": cum_met,
                "false_kill_safe": fk_met,
                "interception_in_band": int_met,
            },
        },
        "drift": {
            "raw_soak_runs": soak_count,
            "cumulative_gated": gated_cum,
            "rolling_gated": gated_runs,
            "window_size": GATE_SOAK_MIN_RUNS,
            "drift_runs": max(0, gated_cum - gated_runs),
        },
        "runtime": {
            "inside_repo": inside_repo,
            "soak_dir": str(soak_root()),
            "outside_met": soak_outside_met,
        },
        "env_vars": {
            "count": env_count,
            "target": 80,
            "met": env_count <= 80,
        },
        "git_cleanliness": {
            "tracked_memory_files": tracked_runtime,
            "clean": runtime_clean,
        },
        "loop_integrity": loop_receipt,
        "anchor": {
            "installed": anchor_installed,
            "epoch": epoch_info.get("epoch") if epoch_info else None,
            "case_count": len(epoch_info.get("cases", [])) if epoch_info else 0,
            "covers_acceptance": anchor_covers_acceptance,
            "covers_ingress": anchor_covers_ingress,
            "dir": str(anchor_dir()),
        },
        "ready_for_promotion": ready_for_promotion,
    }


def format_charter_report(report: dict[str, Any]) -> str:
    """Format the report into clean, human-readable terminal output."""
    acc = report["acceptance"]
    drift = report["drift"]
    env_v = report["env_vars"]
    git_c = report["git_cleanliness"]
    anc = report["anchor"]
    loop = report.get("loop_integrity", {})
    drift_s = loop.get("drift_seconds")

    promo = "READY" if report["ready_for_promotion"] else "BLOCKED (Shadow Mode Maintained)"
    lines = [
        f"Charter Machine Receipt (evolver v{report['version']}, round-{report['round']})",
        (
            f"  Acceptance Gate       : verdict={acc['verdict']}, "
            f"cumulative={acc['gated_cumulative']}, rolling={acc['gated_runs']}"
        ),
        (
            f"  Interception / Risk   : rate={acc['interception_rate']:.2f} "
            f"(met={acc['criteria_met']['interception_in_band']}), "
            f"false_kill={acc['false_kill_risk']} "
            f"(met={acc['criteria_met']['false_kill_safe']})"
        ),
        (
            f"  Window Drift          : {drift['drift_runs']} unwindowed historical runs "
            f"({drift['cumulative_gated']} cum vs {drift['rolling_gated']} rolling)"
        ),
        (
            f"  Loop Integrity        : status={loop.get('status')}, "
            f"drift={drift_s if drift_s is not None else '-'}s "
            f"(threshold {loop.get('threshold_seconds')}s)"
        ),
        (
            f"  Runtime / Worktree    : inside_repo={report['runtime']['inside_repo']} "
            f"(outside_met={report['runtime']['outside_met']}), clean_git={git_c['clean']}"
        ),
        (
            f"  Anchor Suite          : installed={anc['installed']}, epoch={anc['epoch']}, "
            f"cases={anc['case_count']}, covers_acceptance={anc['covers_acceptance']}, "
            f"covers_ingress={anc.get('covers_ingress', True)}"
        ),
        (
            f"  Env Footprint         : {env_v['count']} unique EVOLVER_* "
            f"(target <= {env_v['target']}, met={env_v['met']})"
        ),
        f"  Promotion Status      : {promo}",
    ]
    return "\n".join(lines)


__all__ = [
    "LOOP_STALE_THRESHOLD_S",
    "build_charter_report",
    "count_unique_evolver_envs",
    "format_charter_report",
    "get_tracked_runtime_files",
    "loop_integrity",
]
