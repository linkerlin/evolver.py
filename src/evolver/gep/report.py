"""Evolution run report (S27.4) — per-cycle verdicts, honest negatives.

No Node.js equivalent; evolver.py addition.

Plan 演进方案_wikiskill对照版.md §27.4: a runnable log surface — every cycle's
verdict (accepted / rejected / no improvement), the r_best curve per
measurement domain, and negative results presented AS-IS (wikiskill
docs/RUNS.md culture: rejections are the system working, not failing).
``build_report`` renders markdown from the event ledger + fitness ledger +
wiki layer; ``evolver report`` prints it (and refreshes the patterns
projection first).
"""

from __future__ import annotations

import time
from typing import Any

from evolver.gep.asset_store import read_all_events
from evolver.gep.fitness_state import load_fitness_state
from evolver.gep.paths import get_evolution_dir


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _verdict_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {
        "events": 0,
        "success": 0,
        "failed": 0,
        "unvalidated": 0,
        "improved": 0,
        "no_improvement": 0,
        "baseline_established": 0,
        "acceptance_rejected": 0,
    }
    for evt in events:
        if evt.get("type") != "EvolutionEvent":
            continue
        counts["events"] += 1
        outcome = evt.get("outcome") or {}
        status = str(outcome.get("status", ""))
        if status == "failed":
            counts["failed"] += 1
        elif status == "success":
            counts["success"] += 1
            if outcome.get("unvalidated"):
                counts["unvalidated"] += 1
        gate = evt.get("fitness_gate") or {}
        verdict = str(gate.get("verdict", ""))
        if verdict in counts:
            counts[verdict] += 1
        acc = evt.get("acceptance_result") or {}
        if acc and not acc.get("accepted", True):
            counts["acceptance_rejected"] += 1
    return counts


def _negative_results(events: list[dict[str, Any]], limit: int = 10) -> list[str]:
    """Recent failures / non-improvements, verbatim — no softening."""
    rows: list[str] = []
    for evt in reversed(events):
        if len(rows) >= limit:
            break
        if evt.get("type") != "EvolutionEvent":
            continue
        outcome = evt.get("outcome") or {}
        gate = evt.get("fitness_gate") or {}
        reason = ""
        if str(outcome.get("status")) == "failed":
            reason = f"failed: {outcome.get('error', 'unknown')}"
        elif str(gate.get("verdict")) == "no_improvement":
            reason = f"no_improvement: score={gate.get('score')} r_best={gate.get('r_best')}"
        elif (acc := evt.get("acceptance_result") or {}) and not acc.get("accepted", True):
            reason = f"acceptance_rejected (shadow={bool(acc.get('shadow'))})"
        if reason:
            rows.append(f"- [{evt.get('timestamp', '?')}] run={evt.get('run_id', '?')} — {reason}")
    return rows


def _wiki_counts() -> dict[str, int]:
    counts = {"log_entries": 0, "skill_impact_entries": 0}
    log = get_evolution_dir() / "wiki" / "log.md"
    impact = get_evolution_dir() / "wiki" / "skill-impact.md"
    try:
        if log.exists():
            counts["log_entries"] = sum(
                1
                for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
                if line.startswith("- [")
            )
        if impact.exists():
            counts["skill_impact_entries"] = sum(
                1
                for line in impact.read_text(encoding="utf-8", errors="replace").splitlines()
                if line.startswith("## ")
            )
    except OSError:
        pass
    return counts


def build_report(limit: int = 500) -> str:
    """Render the evolution report as markdown (negative results as-is)."""
    events = read_all_events()[-limit:]
    counts = _verdict_counts(events)
    state = load_fitness_state()
    wiki_counts = _wiki_counts()

    lines = [
        "# Evolution Report",
        "",
        f"Generated: {_ts()} (last {len(events)} events)",
        "",
        "## Verdicts",
        "",
        f"- EvolutionEvents: {counts['events']}",
        f"- success: {counts['success']} (unvalidated: {counts['unvalidated']})",
        f"- failed: {counts['failed']}",
        f"- fitness gate — improved: {counts['improved']}, "
        f"no_improvement: {counts['no_improvement']}, "
        f"baseline_established: {counts['baseline_established']}",
        f"- acceptance rejected (incl. shadow): {counts['acceptance_rejected']}",
        "",
        "## r_best ledger (per measurement domain)",
        "",
    ]
    domains = state.get("domains") or {}
    if domains:
        lines += ["| domain | baseline | r_best | measurements |", "|---|---|---|---|"]
        for name in sorted(domains):
            d = domains[name]
            history_len = len(d.get("history") or [])
            lines.append(f"| {name} | {d.get('baseline')} | {d.get('r_best')} | {history_len} |")
    else:
        lines.append("_No measured fitness yet — the ledger starts at the first measurement._")
    lines += [
        "",
        "## Wiki knowledge layer",
        "",
        f"- decision-log entries: {wiki_counts['log_entries']}",
        f"- skill-impact entries (rejected/non-improving): {wiki_counts['skill_impact_entries']}",
        "",
        "## Negative results (as-is, most recent first)",
        "",
    ]
    negatives = _negative_results(events)
    lines += (
        negatives
        if negatives
        else [
            "_None in window — absence of rejections is a finding, "
            "not a success claim (shadow gates may not have run)._"
        ]
    )
    return "\n".join(lines) + "\n"


__all__ = ["build_report"]
