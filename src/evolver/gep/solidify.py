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




def classify_failure_mode(
    *,
    constraint_violations: list[Any] | None = None,
    protocol_violations: list[Any] | None = None,
    validation: dict[str, Any] | None = None,
    canary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify solidify failure as soft/hard for learning and retry policy."""
    for item in constraint_violations or []:
        text = str(item).upper()
        if "CRITICAL" in text or "DELETED" in text or "DESTRUCTIVE" in text:
            return {
                "mode": "hard",
                "reasonClass": "constraint_destructive",
                "retryable": False,
            }
    if constraint_violations:
        return {"mode": "hard", "reasonClass": "constraint", "retryable": False}
    if protocol_violations:
        return {"mode": "hard", "reasonClass": "protocol", "retryable": False}
    if validation is not None and not bool(validation.get("ok", True)):
        return {"mode": "soft", "reasonClass": "validation", "retryable": True}
    if canary is not None:
        skipped = bool(canary.get("skipped", False))
        ok = bool(canary.get("ok", True))
        if not skipped and not ok:
            return {"mode": "soft", "reasonClass": "canary", "retryable": True}
    return {"mode": "none", "reasonClass": None, "retryable": False}


def adapt_gene_from_learning(
    *,
    gene: dict[str, Any],
    outcome_status: str,
    learning_signals: list[Any] | None = None,
    failure_mode: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mutate *gene* in place with structured learning feedback."""
    tags = [str(s) for s in (learning_signals or []) if s]
    history = gene.setdefault("learning_history", [])
    if not isinstance(history, list):
        gene["learning_history"] = []
        history = gene["learning_history"]
    history.append(
        {
            "outcome": outcome_status,
            "signals": tags,
            "mode": (failure_mode or {}).get("mode"),
            "reasonClass": (failure_mode or {}).get("reasonClass"),
        }
    )
    if outcome_status == "success":
        match = gene.setdefault("signals_match", [])
        if not isinstance(match, list):
            gene["signals_match"] = []
            match = gene["signals_match"]
        for tag in tags:
            if tag.startswith("action:"):
                continue
            if tag not in match:
                match.append(tag)
    else:
        anti = gene.setdefault("anti_patterns", [])
        if not isinstance(anti, list):
            gene["anti_patterns"] = []
            anti = gene["anti_patterns"]
        anti.append(
            {
                "mode": (failure_mode or {}).get("mode"),
                "reasonClass": (failure_mode or {}).get("reasonClass"),
                "signals": tags,
            }
        )
    return gene


def build_soft_failure_learning_signals(
    *,
    signals: list[Any] | None = None,
    failure_reason: str | None = None,
    violations: list[Any] | None = None,
    validation_results: list[Any] | None = None,
) -> list[str]:
    """Extract structured learning tags from a soft validation failure."""
    tags: list[str] = []
    blob_parts: list[str] = [str(failure_reason or "")]
    for sig in signals or []:
        blob_parts.append(str(sig))
    for item in violations or []:
        blob_parts.append(str(item))
    for row in validation_results or []:
        if isinstance(row, dict):
            blob_parts.append(str(row.get("cmd") or row.get("command") or ""))
            blob_parts.append(str(row.get("stderr") or ""))
            blob_parts.append(str(row.get("stdout") or ""))
        else:
            blob_parts.append(str(row))
    blob = " ".join(blob_parts).lower()
    if any(k in blob for k in ("latency", "perf", "performance", "slow", "bottleneck")):
        tags.append("problem:performance")
    if any(k in blob for k in ("timeout", "timed out")):
        tags.append("problem:timeout")
    if any(k in blob for k in ("protocol", "schema", "invalid json")):
        tags.append("problem:protocol")
    if validation_results is not None or "validation" in blob:
        tags.append("risk:validation")
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _normalize_validation_command(cmd: Any) -> tuple[list[str], str]:
    """Return (argv for subprocess, display string for logs/traces)."""
    if isinstance(cmd, list):
        argv = [str(part) for part in cmd]
        return argv, " ".join(argv)
    text = str(cmd)
    return [text], text


def _run_validations(commands: list[Any], cwd: Path) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    overall_ok = True
    started_at = time.time() * 1000.0
    for cmd in commands:
        argv, display = _normalize_validation_command(cmd)
        result: dict[str, Any] = {
            "command": display,
            "ok": False,
            "stdout": "",
            "stderr": "",
        }
        try:
            proc = subprocess.run(
                argv,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=VALIDATION_TIMEOUT_MS / 1000.0,
                shell=False,
                check=False,
            )
            result["ok"] = proc.returncode == 0
            result["stdout"] = (proc.stdout or "")[:2000]
            result["stderr"] = (proc.stderr or "")[:2000]
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

    # Self-Harness A1: empirical acceptance gate (opt-in via
    # EVOLVER_FF_ENABLE_ACCEPTANCE_GATE). Runs after quick validation, before
    # the event is recorded. Reject → rollback + record failure (same path as
    # validation failure). Returns None when the gate is disabled → no-op.
    gate_result: dict[str, Any] | None = None
    try:
        from evolver.gep.acceptance.solidify_hook import gate_for_solidify

        gate_result = gate_for_solidify(last_run, cwd)
    except Exception as gate_exc:  # noqa: BLE001 — gate must never break solidify
        print(f"[solidify] acceptance gate error: {gate_exc}")
        gate_result = None
    if gate_result is not None and not gate_result.accepted:
        rollback_tracked()
        rollback_new_untracked_files(git_list_untracked_files(cwd))
        record_solidify_failure(last_run, error="acceptance_gate_rejected")
        return {
            "ok": False,
            "error": "acceptance_gate_rejected",
            "details": {"acceptance": gate_result.model_dump()},
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
    if gate_result is not None:
        event["acceptance_result"] = gate_result.model_dump()
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


__all__ = [
    "adapt_gene_from_learning",
    "build_soft_failure_learning_signals",
    "classify_failure_mode",
    "solidify",
    "write_state_for_solidify",
]
