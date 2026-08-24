"""Sprint 24 soak calibration — P0+P1 features against a scripted 12-cycle mix.

Probes:
  A. Event projection + cycle state machine + idempotency, fed by REAL
     solidify() successes (10) + scripted failed EvolutionEvents (2, the
     cascade-failure event shape) + per-cycle noise events.
     Invariants checked after every cycle:
       - projections.event_count == len(event log)
       - category-window parity vs an independent inline oracle
       - timeline final stage matches outcome; stages all on the lattice
       - once(cycle_id) fires exactly once
  B. Daily budget gate through real run_preflight_checks (cap=3).
  C. Watchdog staleness helper + `evolver rebuild-views --json` CLI wiring.

Run:  uv run python scripts/soak_sprint24.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
CYCLES = 12
CATEGORIES = ["repair", "optimize", "innovate", "explore"]
VALID_CATEGORIES = set(CATEGORIES)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


def make_workspace(tag: str) -> Path:
    ws = Path(tempfile.mkdtemp(prefix=f"soak24-{tag}-")) / "ws"
    ws.mkdir(parents=True)
    for key, val in {
        "OPENCLAW_WORKSPACE": str(ws),
        "EVOLVER_REPO_ROOT": str(ws),
        "GEP_ASSETS_DIR": str(ws / ".evolver" / "gep"),
        "EVOLUTION_DIR": str(ws / "memory" / "evolution"),
        "MEMORY_DIR": str(ws / "memory"),
        "EVOLVER_HOME": str(ws / ".evomap"),
        "EVOLVER_NO_PARENT_GIT": "1",
    }.items():
        os.environ[key] = val
    _git(ws, "init")
    _git(ws, "config", "user.email", "soak@test")
    _git(ws, "config", "user.name", "soak")
    (ws / "feature.txt").write_text("seed\n", encoding="utf-8")
    _git(ws, "add", "-A")
    _git(ws, "-c", "commit.gpgsign=false", "commit", "-m", "init")
    return ws


def set_flags(**flags: bool) -> None:
    from evolver.gep.feature_flags import invalidate_cache

    for name, value in flags.items():
        os.environ[f"EVOLVER_FF_{name.upper()}"] = "1" if value else "0"
    invalidate_cache()


# --- Probe A ---------------------------------------------------------------


def scripted_failed_event(run_id: str, gene_id: str, category: str) -> dict[str, Any]:
    """The cascade-failure EvolutionEvent shape solidify.py emits."""
    return {
        "type": "EvolutionEvent",
        "id": f"evt_fail_{run_id}",
        "run_id": run_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "gene_id": gene_id,
        "signals": ["log_error"],
        "mutation": {"category": category},
        "blast_radius": {"files_changed": 1, "lines_added": 2, "lines_removed": 1},
        "outcome": {"status": "failed", "score": 0.25, "error": "validation_failed"},
    }


def oracle_category_window(events: list[dict[str, Any]], window: int = 50):
    """Independent reimplementation of mutation._category_stats semantics."""
    stats: dict[str, dict[str, float]] = {}
    for evt in events[-window:]:
        mutation = evt.get("mutation")
        outcome = evt.get("outcome")
        cat = mutation.get("category") if isinstance(mutation, dict) else None
        score = outcome.get("score") if isinstance(outcome, dict) else None
        if cat not in VALID_CATEGORIES or not isinstance(score, (int, float)):
            continue
        row = stats.setdefault(cat, {"attempts": 0.0, "score_sum": 0.0})
        row["attempts"] += 1
        row["score_sum"] += float(score)
    return stats


def probe_a() -> tuple[list[str], Path | None]:
    from evolver.gep.asset_store import append_event_jsonl, read_all_events
    from evolver.gep.cycle_state_machine import STAGE_ORDER, build_cycle_timeline
    from evolver.gep.event_projection import (
        project_events,
        rebuild_projections,
        scored_category_window,
    )
    from evolver.gep.idempotency import already_done, mark_done
    from evolver.gep.solidify import solidify, write_state_for_solidify

    failures: list[str] = []
    ws = make_workspace("a")
    print(f"[A] workspace: {ws}")

    for cycle in range(1, CYCLES + 1):
        run_id = f"run_soak_{cycle:02d}"
        category = CATEGORIES[cycle % len(CATEGORIES)]
        gene_id = f"gene_{cycle % 3}"

        # Real solidify success on odd cycles; scripted cascade-failure
        # event every 4th cycle; noise events every cycle.
        if cycle % 4 == 0:
            append_event_jsonl(scripted_failed_event(run_id, gene_id, category))
        else:
            write_state_for_solidify(
                {
                    "run_id": run_id,
                    "selected_gene_id": gene_id,
                    "signals": ["log_error"],
                    "mutation": {
                        "type": "Mutation",
                        "id": f"mut_{cycle}",
                        "category": category,
                        "validation": [],
                    },
                }
            )
            result = solidify()
            if not result.get("ok"):
                failures.append(f"cycle {cycle}: solidify failed: {result.get('error')}")
                continue

        append_event_jsonl({"type": "cycle_start", "run_id": run_id})
        append_event_jsonl(
            {
                "type": "cycle_end",
                "run_id": run_id,
                "status": "failed" if cycle % 4 == 0 else "success",
            }
        )

        # Invariant 1: projection freshness == log length.
        views = rebuild_projections()
        events = read_all_events()
        if views["event_count"] != len(events):
            failures.append(f"cycle {cycle}: projection count drift")

        # Invariant 2: operator-bandit window parity vs independent oracle.
        projected = scored_category_window(window=50)
        expected = oracle_category_window(events)
        if projected != expected:
            failures.append(f"cycle {cycle}: window parity broken\n {projected}\n {expected}")

        # Invariant 3: timeline stage correctness per outcome.
        timeline = {row["run_id"]: row for row in build_cycle_timeline(events)}
        row = timeline.get(run_id)
        if row is None:
            failures.append(f"cycle {cycle}: timeline row missing")
        else:
            failed_run = cycle % 4 == 0
            want_final = "failed" if failed_run else "solidified"
            if row["stage"] != want_final:
                failures.append(
                    f"cycle {cycle}: final stage {row['stage']} != {want_final}"
                )
            bad_stages = [
                s for s in row["stages_seen"] if s not in STAGE_ORDER
            ]
            if bad_stages:
                failures.append(f"cycle {cycle}: off-lattice stages {bad_stages}")

        # Invariant 4: idempotency exactly-once per cycle.
        mark_done(run_id, "soak_probe")
        if already_done(run_id, "soak_probe") is False:
            failures.append(f"cycle {cycle}: idempotency lost")

    # Cross-check full-log projections one last time (pure view).
    views = project_events(read_all_events())
    genes = views["gene_outcomes"]
    total_attempts = sum(int(g["attempts"]) for g in genes.values())
    print(
        f"[A] done: events={views['event_count']} genes={len(genes)} "
        f"attempts={total_attempts} cycles={len(views['cycle_timeline'])}"
    )
    return failures, ws


# --- Probe B ---------------------------------------------------------------


def probe_b() -> list[str]:
    failures: list[str] = []
    make_workspace("b")
    set_flags(enable_trigger_budget=True)
    os.environ["EVOLVER_MAX_CYCLES_PER_DAY"] = "3"

    from evolver.evolve.guards import run_preflight_checks

    outcomes = []
    for i in range(1, 5):
        result = asyncio.run(run_preflight_checks(is_loop=True))
        outcomes.append((i, result.abort, result.reason))

    for i, abort, reason in outcomes[:3]:
        if abort:
            failures.append(f"[B] cycle {i} unexpectedly aborted: {reason}")
    i, abort, reason = outcomes[3]
    if not (abort and reason and "daily budget exhausted" in reason):
        failures.append(f"[B] cycle 4 did not trip budget gate: {reason}")
    print("[B] preflight outcomes:", [(i, a, r) for i, a, r in outcomes])
    set_flags(enable_trigger_budget=False)
    return failures


# --- Probe C ---------------------------------------------------------------


def probe_c(ws_a: Path | None = None) -> list[str]:
    failures: list[str] = []

    from evolver.ops.health_check import daemon_stall_seconds

    stale = Path(tempfile.mkdtemp(prefix="soak24-c-")) / "cycle_progress.json"
    stale_ts = int(time.time() * 1000) - 1900_000
    stale.write_text(json.dumps({"updated_at": stale_ts}), encoding="utf-8")
    stall = daemon_stall_seconds(progress_path=stale)
    if stall is None or stall < 1800:
        failures.append(f"[C] watchdog staleness wrong: {stall}")
    fresh = stale.with_name("fresh.json")
    fresh.write_text(json.dumps({"updated_at": int(time.time() * 1000)}), encoding="utf-8")
    fresh_stall = daemon_stall_seconds(progress_path=fresh)
    if fresh_stall is None or fresh_stall > 5.0:
        failures.append(f"[C] fresh progress misread as stalled: {fresh_stall}")

    # CLI wiring: rebuild-views --json against workspace A's event log.
    if ws_a is not None:
        cli_env = os.environ.copy()
        for key, val in {
            "OPENCLAW_WORKSPACE": str(ws_a),
            "EVOLVER_REPO_ROOT": str(ws_a),
            "GEP_ASSETS_DIR": str(ws_a / ".evolver" / "gep"),
            "EVOLUTION_DIR": str(ws_a / "memory" / "evolution"),
            "MEMORY_DIR": str(ws_a / "memory"),
            "EVOLVER_HOME": str(ws_a / ".evomap"),
        }.items():
            cli_env[key] = val
        proc = subprocess.run(
            ["uv", "run", "python", "-m", "evolver", "rebuild-views", "--json"],
            cwd=REPO,
            capture_output=True,
            text=True,
            env=cli_env,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            failures.append(f"[C] rebuild-views exited {proc.returncode}: {proc.stderr[-300:]}")
        else:
            try:
                views = json.loads(proc.stdout)
                if views.get("event_count") != 36:
                    failures.append(
                        f"[C] CLI projection count {views.get('event_count')} != 36"
                    )
                print(
                    f"[C] CLI rebuild-views ok: events={views.get('event_count')} "
                    f"cycles={len(views.get('cycle_timeline') or [])} "
                    f"genes={len(views.get('gene_outcomes') or {})}"
                )
            except json.JSONDecodeError as exc:
                failures.append(f"[C] rebuild-views JSON unparsable: {exc}")
    return failures


def main() -> int:
    t0 = time.time()
    all_failures: list[str] = []

    fa, ws_a = probe_a()
    all_failures += fa
    fb = probe_b()
    all_failures += fb
    fc = probe_c(ws_a)
    all_failures += fc

    elapsed = time.time() - t0
    print(f"\n=== Sprint 24 soak calibration: {elapsed:.1f}s ===")
    if all_failures:
        print(f"FAILURES ({len(all_failures)}):")
        for f in all_failures:
            print(f"  - {f}")
        return 1
    print("ALL INVARIANTS GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
