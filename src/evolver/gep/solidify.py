"""Main solidify cycle: apply gene, run validations, persist results, publish.

Equivalent to evolver/src/gep/solidify.js (obfuscated).
"""

from __future__ import annotations

import json
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any

from evolver.config import VALIDATION_TIMEOUT_MS
from evolver.gep.asset_store import append_event_jsonl, read_json_if_exists
from evolver.gep.cognition import post_solidify_hooks, record_solidify_failure
from evolver.gep.execution_trace import build_execution_trace
from evolver.gep.git_ops import (
    capture_diff_snapshot,
    git_list_changed_files,
    git_list_untracked_files,
    is_git_repo,
    rollback_new_untracked_files,
    rollback_tracked,
)
from evolver.gep.paths import (
    get_solidify_state_path,
    get_workspace_root,
)
from evolver.gep.validation_report import build_validation_report
from evolver.ops.narrative import record_narrative_and_reflection


def write_state_for_solidify(last_run: dict[str, Any]) -> None:
    """Write the pending evolution run to the solidify state file."""
    path = get_solidify_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    state = read_json_if_exists(path) or {}
    state["last_run"] = last_run
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_solidify_state() -> dict[str, Any] | None:
    path = get_solidify_state_path()
    return read_json_if_exists(path)


def _run_validations(commands: list[str], cwd: Path) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    overall_ok = True
    started_at = time.time() * 1000.0
    for cmd in commands:
        result = {"command": cmd, "ok": False, "stdout": "", "stderr": ""}
        try:
            proc = subprocess.run(
                cmd if isinstance(cmd, list) else [cmd],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=VALIDATION_TIMEOUT_MS / 1000.0,
                shell=False,
            )
            result["ok"] = proc.returncode == 0
            result["stdout"] = proc.stdout[:2000]
            result["stderr"] = proc.stderr[:2000]
        except Exception as exc:
            result["stderr"] = str(exc)[:500]
        if not result["ok"]:
            overall_ok = False
        results.append(result)
    finished_at = time.time() * 1000.0
    return {
        "ok": overall_ok,
        "results": results,
        "started_at": started_at,
        "finished_at": finished_at,
    }


def _compute_blast_radius() -> dict[str, int]:
    cwd = get_workspace_root()
    changed = git_list_changed_files(cwd)
    untracked = git_list_untracked_files(cwd)
    files = len(set(changed + untracked))
    lines = 0
    for rel in changed + untracked:
        p = cwd / rel
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                lines += sum(1 for _ in f)
        except OSError:
            pass
    return {"files": files, "lines": lines}


def solidify(
    *,
    mutation_override: dict[str, Any] | None = None,
    skip_validation: bool = False,
) -> dict[str, Any]:
    """Run a solidify cycle."""
    state = _read_solidify_state()
    if not state or not state.get("last_run"):
        return {"ok": False, "error": "no_pending_run"}

    last_run = state["last_run"]
    cwd = get_workspace_root()

    if not is_git_repo(cwd):
        return {"ok": False, "error": "not_a_git_repo"}

    mutation = mutation_override or last_run.get("mutation", {})
    validation_commands = mutation.get("validation") or []

    validation_result: dict[str, Any] | None = None
    validation_report: dict[str, Any] | None = None
    if not skip_validation and validation_commands:
        validation_result = _run_validations(validation_commands, cwd)
        try:
            validation_report = build_validation_report(
                gene_id=last_run.get("selected_gene_id"),
                commands=[r.get("command", "") for r in validation_result["results"]],
                results=validation_result["results"],
                started_at=validation_result.get("started_at"),
                finished_at=validation_result.get("finished_at"),
            )
        except Exception:
            validation_report = None
        if not validation_result["ok"]:
            rollback_tracked()
            rollback_new_untracked_files(git_list_untracked_files(cwd))
            record_solidify_failure(last_run, error="validation_failed")
            details: dict[str, Any] = dict(validation_result)
            if validation_report is not None:
                details["validation_report"] = validation_report
            return {
                "ok": False,
                "error": "validation_failed",
                "details": details,
            }

    blast_radius = _compute_blast_radius()
    diff_snapshot = capture_diff_snapshot(cwd)

    # Build execution trace from validation results
    trace: list[dict[str, Any]] = []
    if validation_result:
        commands = [r["command"] for r in validation_result["results"]]
        outputs = [r["stdout"] + "\n" + r["stderr"] for r in validation_result["results"]]
        trace = build_execution_trace(commands, outputs)

    event: dict[str, Any] = {
        "type": "EvolutionEvent",
        "id": f"evt_{int(time.time() * 1000)}_{secrets.token_hex(4)}",
        "run_id": last_run.get("run_id") or last_run.get("mutation", {}).get("id"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime())
        + f"{int((time.time() % 1) * 1000):03d}Z",
        "gene_id": last_run.get("selected_gene_id"),
        "signals": last_run.get("signals", []),
        "mutation": mutation,
        "blast_radius": blast_radius,
        "diff_snapshot": diff_snapshot[:2000],
        "outcome": {"status": "success", "score": 1.0},
        "execution_trace": trace,
    }
    if validation_report is not None:
        event["validation_report"] = validation_report
    append_event_jsonl(event)

    # Generate narrative and reflection
    try:
        record_narrative_and_reflection(event)
    except Exception:
        pass

    try:
        post_solidify_hooks(event, last_run)
    except Exception:
        pass

    # Update solidify state
    state["last_solidify"] = {
        "run_id": last_run.get("run_id"),
        "timestamp": event["timestamp"],
        "outcome": "success",
    }
    tmp = get_solidify_state_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp.replace(get_solidify_state_path())

    return {"ok": True, "event_id": event["id"], "blast_radius": blast_radius}


__all__ = ["solidify", "write_state_for_solidify"]
