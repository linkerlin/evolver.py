"""Main solidify cycle: apply gene, run validations, persist results, publish.

Equivalent to evolver/src/gep/solidify.js (obfuscated).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Final

from evolver.config import (
    ACCEPTANCE_SHADOW,
    FITNESS_CASCADE_COMMANDS,
    VALIDATION_TIMEOUT_MS,
)
from evolver.config import (
    FITNESS_CASCADE_COMMANDS as _CONFIG_FITNESS_CASCADE_COMMANDS,
)
from evolver.gep.acceptance.solidify_hook import gate_or_none
from evolver.gep.anchor import run_anchor_suite, touches_verifier_surface
from evolver.gep.asset_store import (
    append_event_jsonl,
    read_json_if_exists,
)
from evolver.gep.cognition import post_solidify_hooks, record_solidify_failure
from evolver.gep.execution_trace import build_execution_trace
from evolver.gep.feature_flags import is_enabled
from evolver.gep.fitness_state import record_measurement
from evolver.gep.git_ops import (
    capture_diff_snapshot,
    git_list_changed_files,
    git_list_untracked_files,
    is_git_repo,
    restore_rejected_stash,
    rollback_new_untracked_files,
    rollback_tracked,
    snapshot_rejected_worktree,
)
from evolver.gep.paths import (
    discover_git_candidates,
    get_repo_root,
    get_solidify_state_path,
    get_workspace_root,
    resolve_legacy_read_path,
)
from evolver.gep.validation_report import build_validation_report
from evolver.ops.narrative import record_narrative_and_reflection

logger = logging.getLogger(__name__)


def _now_iso_ms() -> str:
    """Timestamp with millisecond precision (shared by events + ledgers)."""
    return (
        time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime()) + f"{int((time.time() % 1) * 1000):03d}Z"
    )


def _timing_block(validation_result: dict[str, Any]) -> dict[str, Any]:
    """RSI P0-2 (round-16): per-stage validation durations, consumed by the
    meta-report efficiency panel (time per validated gain, not just rounds).

    Round-19: attached on failure events too — a rejected cascade burns the
    same validation seconds, and the efficiency metric was blind to its most
    expensive path (two round-16 rejections left zero cost trace).

    Round-20: ``total_ms`` prefers the monotonic ``duration_ms`` measured by
    ``_run_validations``; the wall-clock diff stays only as a fallback for
    legacy results that predate the field.
    """
    total_ms = validation_result.get("duration_ms")
    if total_ms is None:
        total_ms = round(
            float(validation_result.get("finished_at", 0))
            - float(validation_result.get("started_at", 0))
        )
    block: dict[str, Any] = {
        "total_ms": total_ms,
        "stages": [
            {
                "command": str(r.get("command", ""))[:120],
                "ok": r.get("ok"),
                "duration_ms": r.get("duration_ms"),
            }
            for r in validation_result.get("results", [])
        ],
    }
    if validation_result.get("tier"):
        block["tier"] = validation_result["tier"]
    if validation_result.get("scope"):
        block["scope"] = validation_result["scope"]
    return block


def _failure_event(
    last_run: dict[str, Any],
    mutation: dict[str, Any],
    blast_radius: dict[str, Any],
    outcome: dict[str, Any],
    *,
    validation_result: dict[str, Any] | None = None,
    eval_meta: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Shared skeleton for failed EvolutionEvents (review dedup): every
    rejection path — cascade, novelty, acceptance, fitness — lands the same
    auditable shape. When validation ran before the rejection, its timing
    rides along (cost visibility for the efficiency panel), and so does the
    eval-isolation meta (round-23: a rejected event must be able to prove it
    ran in the clean worktree — same filter as the success path)."""
    event = {
        "type": "EvolutionEvent",
        "id": f"evt_{int(time.time() * 1000)}_{secrets.token_hex(4)}",
        "run_id": last_run.get("run_id") or (last_run.get("mutation") or {}).get("id"),
        "timestamp": _now_iso_ms(),
        "gene_id": last_run.get("selected_gene_id"),
        "signals": last_run.get("signals", []),
        "mutation": mutation,
        "blast_radius": blast_radius,
        "outcome": outcome,
        **extra,
        **_lineage_fields(),
    }
    if validation_result is not None:
        event["validation_timing"] = _timing_block(validation_result)
    if eval_meta and eval_meta.get("reason") not in ("flag_off", "skipped"):
        event["eval_workspace"] = eval_meta
    return event


# Stored scene budget for failure episodes and success events. Applied inside
# capture_diff_snapshot so a large tracked diff cannot push untracked hunks
# past the cut (DEBUG #57).
_STORED_DIFF_CHARS: Final = 2000


def _failure_diff(cwd: Path) -> str:
    """The mutation's diff, captured before rollback. After rollback it is gone."""
    return capture_diff_snapshot(cwd, max_chars=_STORED_DIFF_CHARS)


def _remember_failure_scene(
    event: dict[str, Any],
    *,
    validation_result: dict[str, Any] | None = None,
    fitness_verdict: dict[str, Any] | None = None,
    gate: dict[str, Any] | None = None,
) -> str:
    """Persist the immutable scene of a settled failure. Returns the event id.

    Same shape as the success scene (event, checks, gate), keyed by the event
    id so the cycle boundary can record it. This does not write the episode:
    ``solidify`` stays off the episode-writer call graph.
    """
    event_id = str(event.get("id") or "")
    if not event_id:
        return ""
    run_id = str(event.get("run_id") or "unknown")
    with contextlib.suppress(Exception):
        from evolver.gep.evidence import save_evidence

        save_evidence(
            run_id,
            event_id,
            {
                "event": event,
                "validation_result": validation_result,
                "fitness_verdict": fitness_verdict,
                "gate": gate,
            },
        )
    return event_id


def write_state_for_solidify(last_run: dict[str, Any]) -> None:
    """Write the pending evolution run to the solidify state file (U-6 atomic + stamped)."""
    import os

    path = get_solidify_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    state = read_json_if_exists(path) or {}
    now_iso = _now_iso_ms()
    enriched_run = dict(last_run or {})
    run_id = str(
        enriched_run.get("run_id")
        or (enriched_run.get("mutation") or {}).get("id")
        or f"run_{int(time.time() * 1000)}_{secrets.token_hex(3)}"
    )
    enriched_run["run_id"] = run_id
    enriched_run["updated_at"] = now_iso
    state["last_run"] = enriched_run
    state["run_id"] = run_id
    state["updated_at"] = now_iso
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def record_landed_gene_ids(ids: list[str]) -> None:
    """Persist distilled gene ids onto the pending solidify run (lineage)."""
    state = _read_solidify_state() or {}
    last_run = dict(state.get("last_run") or {})
    last_run["landed_gene_ids"] = [str(i) for i in ids if i]
    write_state_for_solidify(last_run)


def _annotate_mutation_lineage(
    last_run: dict[str, Any], mutation: dict[str, Any]
) -> dict[str, Any]:
    out = dict(mutation or {})
    selected = last_run.get("selected_gene_id")
    if selected and not out.get("gene_id"):
        out["gene_id"] = selected
    landed = [str(x) for x in (last_run.get("landed_gene_ids") or []) if x]
    if landed:
        out["landed_gene_id"] = landed[0]
        out["landed_gene_ids"] = landed
    return out


def _read_solidify_state() -> dict[str, Any] | None:
    primary = get_solidify_state_path()
    legacy = get_workspace_root() / "memory" / "evolution" / "evolution_solidify_state.json"
    path = resolve_legacy_read_path(primary, [legacy])
    return read_json_if_exists(path)


def _mark_run_settled(run_id: str, error: str) -> None:
    """Record a judged failure as a finished settle (``last_solidify``).

    回放即裁决: a failure with an event is a closed round — the failure
    episode is already written at the cycle boundary, so the pending run is
    consumed and the loop moves on instead of wedging on pending_solidify
    (the wedge the ``pending_redirect_loop`` fuse used to paper over).
    Idempotent: a retry of the same run then answers ``already_solidified``.
    """
    if not run_id:
        return
    try:
        state = _read_solidify_state() or {}
        state["last_solidify"] = {
            "run_id": run_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
            "outcome": "failed",
            "error": error,
        }
        path = get_solidify_state_path()
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except Exception:
        logger.warning("[solidify] failed-settle bookkeeping skipped", exc_info=True)


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


def _normalize_validation_command(cmd: Any) -> tuple[list[str], str, int | None]:
    """Return (argv for subprocess, display string, timeout_ms override).

    Accepts a plain string, an argv list, or a Sprint 22.2 dict spec
    ``{"command": str|list, "timeout_ms": int}`` (engine-owned fitness cascade).
    """
    timeout_ms: int | None = None
    if isinstance(cmd, dict):
        timeout_ms = cmd.get("timeout_ms")
        cmd = cmd.get("command")
    if isinstance(cmd, list):
        argv = [str(part) for part in cmd]
        return argv, " ".join(argv), timeout_ms
    text = str(cmd)
    return [text], text, timeout_ms


_VALIDATION_HEAD_CHARS = 1200
_VALIDATION_TAIL_CHARS = 2800


def _bounded_output(text: str | None) -> str:
    """Keep the head AND tail of validation output.

    pytest puts its failure summary (``FAILED ...`` lines, the ``N passed``
    rate the cascade scorer parses) at the END of stdout — a head-only cap
    discarded exactly the bytes needed to diagnose a failed gate.
    """
    text = text or ""
    if len(text) <= _VALIDATION_HEAD_CHARS + _VALIDATION_TAIL_CHARS:
        return text
    return (
        text[:_VALIDATION_HEAD_CHARS] + "\n…[output truncated]…\n" + text[-_VALIDATION_TAIL_CHARS:]
    )


def _validation_env() -> dict[str, str]:
    """Subprocess env for validation commands (shared helper, round-14).

    Lives in :mod:`evolver.gep.validation_env` now — the acceptance gate's
    pytest subprocesses needed the same PATH normalization; kept as a thin
    alias so existing call sites and tests stay put.
    """
    from evolver.gep.validation_env import validation_env

    return validation_env()


def _run_validations(
    commands: list[Any],
    cwd: Path,
    *,
    cascade: bool = False,
) -> dict[str, Any]:
    """Run validation commands; ``cascade`` short-circuits on first failure.

    Round-20: durations come from ``time.monotonic()`` — the wall clock
    (``time.time()``) absorbs system sleep and NTP steps, which once billed
    a 5.1h laptop sleep to a 208s pytest stage (88x). ``started_at`` /
    ``finished_at`` stay wall-clock epoch ms: they are timestamps for the
    ValidationReport contract, never a duration source.
    """
    results: list[dict[str, Any]] = []
    overall_ok = True
    started_at = time.time() * 1000.0
    started_mono = time.monotonic() * 1000.0
    for cmd in commands:
        argv, display, timeout_ms = _normalize_validation_command(cmd)
        result: dict[str, Any] = {
            "command": display,
            "ok": False,
            "stdout": "",
            "stderr": "",
            "duration_ms": None,
        }
        timeout_s = (
            timeout_ms / 1000.0 if timeout_ms is not None else VALIDATION_TIMEOUT_MS / 1000.0
        )
        stage_t0 = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                shell=False,
                check=False,
                env=_validation_env(),
            )
            result["ok"] = proc.returncode == 0
            result["stdout"] = _bounded_output(proc.stdout)
            result["stderr"] = _bounded_output(proc.stderr)
        except Exception as exc:
            result["stderr"] = str(exc)[:500]
        result["duration_ms"] = round((time.monotonic() - stage_t0) * 1000.0)
        if not result["ok"]:
            overall_ok = False
        results.append(result)
        if cascade and not result["ok"]:
            break
    finished_at = time.time() * 1000.0
    return {
        "ok": overall_ok,
        "results": results,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": round(time.monotonic() * 1000.0 - started_mono),
    }


def _parse_pytest_rate(text: str) -> float | None:
    """Parse a pytest summary line into a pass rate (0.0 to 1.0), else None."""
    if not text:
        return None
    passed_m = re.search(r"(\d+) passed", text)
    if not passed_m:
        return None
    p = int(passed_m.group(1))
    failed_m = re.search(r"(\d+) failed", text)
    f = int(failed_m.group(1)) if failed_m else 0
    err = sum(int(m.group(1)) for m in re.finditer(r"(\d+) errors?\b", text))
    denom = p + f + err
    if denom <= 0:
        return None
    return p / denom


def _cascade_score(results: list[dict[str, Any]]) -> float:
    """Partial credit for a failed cascade: passed stages count fully; the
    failing pytest stage contributes its pass rate (Sprint 22.2 fitness)."""
    total = len(results)
    if total == 0:
        return 0.0
    score = float(sum(1 for r in results if r.get("ok")))
    if score == total:
        return 1.0
    for r in results:
        if not r.get("ok"):
            rate = _parse_pytest_rate(f"{r.get('stdout') or ''}\n{r.get('stderr') or ''}")
            if rate is not None:
                score += rate
            break
    return round(max(0.0, min(1.0, score / total)), 4)


def _wiki_rejection(
    error: str,
    last_run: dict[str, Any],
    *,
    score: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """S27: one rejected mutation = one wiki evidence entry. Best-effort."""
    with contextlib.suppress(Exception):
        from evolver.gep.wiki import append_skill_impact

        metadata: dict[str, Any] = {
            "gene_id": last_run.get("selected_gene_id"),
            "signals": last_run.get("signals", []),
            "error": error,
        }
        if score is not None:
            metadata["score"] = score
        if extra:
            metadata.update(extra)
        append_skill_impact(
            f"{error}: {last_run.get('selected_gene_id') or 'unknown'}",
            "Mutation rejected and rolled back. Do not repeat this approach unchanged.",
            metadata=metadata,
        )


def _wiki_record_outcome(
    event: dict[str, Any],
    fitness_verdict: dict[str, Any] | None,
    last_run: dict[str, Any],
) -> None:
    """S27: project one solidify outcome into the wiki knowledge layer."""
    from evolver.gep.wiki import append_log, append_skill_impact

    gene_id = last_run.get("selected_gene_id") or "unknown"
    outcome = event.get("outcome") or {}
    if fitness_verdict is not None and fitness_verdict["verdict"] == "no_improvement":
        append_skill_impact(
            f"no_improvement: {gene_id}",
            "Mutation passed validation but measured no improvement over r_best "
            "(shadow-rejected). Do not repeat this approach unchanged.",
            metadata={
                "event_id": event["id"],
                "gene_id": gene_id,
                "score": fitness_verdict["score"],
                "r_best": fitness_verdict["r_best"],
            },
        )
        return
    append_log(
        f"accepted: gene={gene_id} score={outcome.get('score')} "
        f"run={last_run.get('run_id')} event={event['id']}"
    )


def _apply_acceptance_gate(
    gate_result: Any,
    last_run: dict[str, Any],
    cwd: Path,
    *,
    validation_result: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Handle a rejection from the acceptance gate; None → gate passed/absent."""
    if gate_result is None or gate_result.accepted:
        return None
    # Sprint 22.5 shadow mode: record the verdict on the event but never
    # enforce (gray-scale — measure interception/false-kill rates first).
    if ACCEPTANCE_SHADOW:
        return None
    diff_snapshot = _failure_diff(cwd)
    failed_blast = _compute_blast_radius()
    snapshot_rejected_worktree(
        cwd,
        run_id=str(last_run.get("run_id") or ""),
        disposable_untracked=_disposable_untracked(cwd),
        reason="fitness_gate_no_improvement",
    )
    rollback_tracked(cwd=cwd, include_untracked=False)
    rollback_new_untracked_files(_disposable_untracked(cwd), cwd=cwd)
    record_solidify_failure(last_run, error="acceptance_gate_rejected")
    _wiki_rejection("acceptance_gate_rejected", last_run)
    gate = gate_result.model_dump()
    event = _append_failure_event(
        last_run,
        cwd,
        blast_radius=failed_blast,
        error="acceptance_gate_rejected",
        validation_result=validation_result,
        diff_snapshot=diff_snapshot,
    )
    result: dict[str, Any] = {
        "ok": False,
        "error": "acceptance_gate_rejected",
        "details": {"acceptance": gate},
    }
    if event is not None:
        result["event_id"] = _remember_failure_scene(
            event, validation_result=validation_result, gate=gate
        )
    return result


def _hypothesis_rejection(
    last_run: dict[str, Any],
    cwd: Path,
    reason: str,
) -> dict[str, Any]:
    """配对会话 §5.3: refuse a Candidate that never stated one hypothesis.

    Checked before the val gate and before the expensive cascade: a Candidate
    that cannot say what it is testing does not get to be measured, and its
    absence of a claim must never be laundered into a publish by scoring.
    """
    diff_snapshot = _failure_diff(cwd)
    failed_blast = _compute_blast_radius()
    snapshot_rejected_worktree(
        cwd,
        run_id=str(last_run.get("run_id") or ""),
        disposable_untracked=_disposable_untracked(cwd),
        reason="fitness_gate_no_improvement",
    )
    rollback_tracked(cwd=cwd, include_untracked=False)
    rollback_new_untracked_files(_disposable_untracked(cwd), cwd=cwd)
    record_solidify_failure(last_run, error="hypothesis_missing", score=None)
    failure = _failure_event(
        last_run,
        last_run.get("mutation", {}),
        failed_blast,
        {"status": "failed", "error": "hypothesis_missing", "detail": reason},
        validation_result=None,
        diff_snapshot=diff_snapshot,
    )
    append_event_jsonl(failure)
    from evolver.ops.open_box import attach_next_steps

    return attach_next_steps(
        {
            "ok": False,
            "error": "hypothesis_missing",
            "event_id": _remember_failure_scene(failure),
            # Same soft-failure contract as the pack gate: the round is over but
            # the loop keeps running with repair bias.
            "failure_mode": {"mode": "soft", "reasonClass": "hypothesis", "retryable": True},
            "next_action": "evolve_begin",
            "details": {"hypothesis": reason},
        }
    )


def _seal_rejection(
    last_run: dict[str, Any],
    cwd: Path,
    where: str,
    reason: str,
) -> dict[str, Any]:
    """配对会话 §5.2: a Candidate whose context carried val material."""
    diff_snapshot = _failure_diff(cwd)
    failed_blast = _compute_blast_radius()
    snapshot_rejected_worktree(
        cwd,
        run_id=str(last_run.get("run_id") or ""),
        disposable_untracked=_disposable_untracked(cwd),
        reason="fitness_gate_no_improvement",
    )
    rollback_tracked(cwd=cwd, include_untracked=False)
    rollback_new_untracked_files(_disposable_untracked(cwd), cwd=cwd)
    record_solidify_failure(last_run, error="val_seal_breach", score=None)
    failure = _failure_event(
        last_run,
        last_run.get("mutation", {}),
        failed_blast,
        {
            "status": "failed",
            "error": "val_seal_breach",
            "where": where,
            "detail": reason,
        },
        validation_result=None,
        diff_snapshot=diff_snapshot,
    )
    append_event_jsonl(failure)
    return {
        "ok": False,
        "error": "val_seal_breach",
        "event_id": _remember_failure_scene(failure),
        "failure_mode": {"mode": "soft", "reasonClass": "val_seal", "retryable": True},
        "next_action": "swarm_tick",
        "details": {"val_seal": {"where": where, "detail": reason}},
    }


#: Workbench-draft fix guidance is capped at exactly three human lines
#: (演进方案.md 支柱一: 3 行人话修复指引).
ACTIONABLE_FIX_MAX_LINES: Final = 3


def _workbench_preserved_line(run_id: str) -> str:
    return (
        "Your patch is preserved in place (backup: rejected_stashes/"
        f"{run_id or '<run_id>'}) — nothing was deleted."
    )


def _first_error_location(stderr: str) -> str:
    """``file.py:12`` from the first locatable error frame, else ``""``.

    Understands both ``path.py:12`` (ruff/mypy style) and Python tracebacks
    (``File "...", line 12``). Windows drive letters survive."""
    match = re.search(r"((?:[A-Za-z]:[\\/])?[A-Za-z0-9_\-./\\]+\.\w+):(\d+)", stderr)
    if match:
        return f"{match.group(1)}:{match.group(2)}"
    tb = re.search(r'File "(.+)", line (\d+)', stderr)
    if tb:
        return f"{tb.group(1)}:{tb.group(2)}"
    return ""


def _actionable_fix_from_validation(
    validation_result: dict[str, Any],
    run_id: str,
) -> list[str]:
    """Exactly three human fix lines, each with file:line precision when the
    failing stage's stderr names a location (pytest/ruff/mypy all do)."""
    lines: list[str] = []
    first_detail = ""
    for result in validation_result.get("results", []):
        if not isinstance(result, dict) or result.get("ok"):
            continue
        cmd = str(result.get("command") or "validation").strip()
        stderr = str(result.get("stderr") or "") or str(result.get("stdout") or "")
        where = _first_error_location(stderr)
        location = f" (first at {where})" if where else ""
        first_line = next((ln.strip() for ln in stderr.splitlines() if ln.strip()), "")
        if not first_detail and first_line:
            first_detail = first_line[:120]
        lines.append(f"`{cmd}` failed{location}. Fix that first error.")
        if len(lines) >= ACTIONABLE_FIX_MAX_LINES - 1:
            break
    if len(lines) < ACTIONABLE_FIX_MAX_LINES - 1 and first_detail:
        lines.append(f"First error says: {first_detail}")
    # Exactly three lines, always: pad when the failing stage printed nothing
    # usable (round-121 review: silent failures used to yield two lines).
    while len(lines) < ACTIONABLE_FIX_MAX_LINES - 1:
        lines.append("Re-run the failing command locally to see its full error output.")
    lines.append(_workbench_preserved_line(run_id))
    return lines[:ACTIONABLE_FIX_MAX_LINES]


def _actionable_fix_from_verdict(verdict: dict[str, Any], run_id: str) -> list[str]:
    """Three human fix lines for a fitness-gate miss (drop/flat/regression)."""
    reason = str(verdict.get("reason") or "no_improvement").strip()
    score = verdict.get("score")
    bar = verdict.get("baseline")
    measured = score is not None and bar is not None
    bar_text = f" (score {score} vs baseline {bar})" if measured else ""
    return [
        f"Fitness gate: {reason}{bar_text} — the change did not strictly beat the Parent.",
        "Improve or revert the change locally; the patch was not discarded.",
        _workbench_preserved_line(run_id),
    ]


def _retract_this_runs_distilled_assets(run_id: str) -> None:
    """支柱一 vault freeze: a draft_preserved settle retracts the distilled
    assets the host staged for this run (round-121 review — swarm_distill
    installs before the gates judge; never best-effort silent)."""
    try:
        from evolver.gep.asset_store import retract_distilled_assets

        retract_distilled_assets(run_id)
    except Exception:
        logger.warning("[solidify] distilled-asset retraction failed", exc_info=True)


def _bench_pack_rejection(
    last_run: dict[str, Any],
    cwd: Path,
    verdict: dict[str, Any],
    validation_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the workbench-draft rejection for a Candidate that missed the bar.

    算子即基因 v1.114.0 (支柱一): a non-improvement is a *draft*, not a crime —
    the patch stays in the worktree (backed up to ``rejected_stashes/<run_id>``
    first), the return is an honest ``ok=False`` with a 3-line fix, and the
    vault sees strictly zero new positive assets. Shared by every non-accept
    fitness outcome (drop, flat, regression, a damaged gate) so none of them
    can quietly differ in what happens to the working tree.
    """
    run_id = str(last_run.get("run_id") or "")
    diff_snapshot = _failure_diff(cwd)
    failed_blast = _compute_blast_radius()
    stash_info = snapshot_rejected_worktree(
        cwd,
        run_id=run_id,
        disposable_untracked=_disposable_untracked(cwd),
        reason="fitness_gate_no_improvement",
    )
    reason = str(verdict.get("reason") or "unknown")
    _retract_this_runs_distilled_assets(run_id)
    record_solidify_failure(last_run, error="bench_pack_rejected", score=verdict.get("score"))
    _wiki_rejection("bench_pack_rejected", last_run, score=verdict.get("score"))
    failure = _failure_event(
        last_run,
        last_run.get("mutation", {}),
        failed_blast,
        {
            "status": "failed",
            "score": verdict.get("score"),
            "error": "bench_pack_rejected",
            "pack_reason": reason,
        },
        validation_result=validation_result,
        bench_pack=verdict,
        diff_snapshot=diff_snapshot,
    )
    # Single append (the rich event, not the flag-gated skeleton) — the DGM
    # variant archive and the diagnostic ledger still see the rejection.
    append_event_jsonl(failure)
    _maybe_record_variant(failure, validation_result)
    _maybe_open_diagnostic_entry(failure, validation_result)
    return {
        "ok": False,
        "outcome": "draft_preserved",
        "error": "bench_pack_rejected",
        "event_id": _remember_failure_scene(failure, validation_result=validation_result),
        "actionable_fix": _actionable_fix_from_verdict(verdict, run_id),
        "rejected_stash": stash_info,
        # A missed fitness bar is not a crash: the patch stays in the worktree
        # and the loop continues with repair bias (structured field mirrors
        # prose — round-57 lesson; the swarm wrapper only fills absent keys).
        "failure_mode": {"mode": "soft", "reasonClass": "bench_pack", "retryable": True},
        "next_action": "swarm_tick",
        "details": {"bench_pack": verdict},
    }


def _apply_bench_pack_gate(
    last_run: dict[str, Any],
    cwd: Path,
    *,
    validation_result: dict[str, Any] | None = None,
    declaration: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Charter 配对会话 + 双轨门 (v1.114.0): frozen val pack decides.

    ONLY a strict improvement over the Parent publishes as a full Accept.

    双轨拆分 (算子即基因 v1.114.0): 适应度裁决 (drop/flat/regression) 与验证
    失败是诚实拒绝 -- 返回 ok=False / draft_preserved, 补丁原位保留 (备份
    rejected_stashes/<run_id>) 并附 3 行 actionable_fix, 不进金库、不写 Parent.
    仅首轮环境缺口 (no_baseline/pack_absent/unmeasured) soft-accept with
    warnings + next_steps, 让宿主走完循环并写入经验; soft-accept 同样不写
    Parent、不解 val 密封. Returns ``(rejection, verdict)``.

    Only hard blocks (secrets, protected state, val_seal) trigger rejection + rollback.
    """
    try:
        from evolver.bench.frozen_gate import (
            enrich_soft_accept,
            gate_verdict,
            is_usability_soft_reason,
        )

        verdict = gate_verdict(declaration=declaration)
    except Exception:
        logger.warning("[bench-pack-gate] evaluation failed — rejecting", exc_info=True)
        verdict = {
            "armed": False,
            "accept": False,
            "verdict": "reject",
            "reason": "gate_error",
        }

    if verdict is None or not isinstance(verdict, dict):
        verdict = {
            "armed": False,
            "accept": False,
            "verdict": "reject",
            "reason": "gate_error",
        }

    if verdict.get("verdict") == "accept" and verdict.get("accept") is True:
        return None, verdict

    reason = str(verdict.get("reason") or "")
    if is_usability_soft_reason(reason):
        # Soft-accept: proceed with warnings; never fake a Parent baseline.
        return None, enrich_soft_accept(verdict)

    return _bench_pack_rejection(last_run, cwd, verdict, validation_result), verdict


def _maybe_record_variant(
    event: dict[str, Any],
    validation_result: dict[str, Any] | None,
) -> None:
    """RSI P1-3 (round-40): archive rejected-but-retained variants (DGM).

    Classifies the rejection where the stage stderr still lives (the
    persisted event slims it away) and appends to the variant archive.
    Never raises — archive trouble must not break the rejection flow."""
    try:
        from evolver.gep.variant_archive import classify_rejection, record_variant

        record_variant(event, classify_rejection(validation_result))
    except Exception:
        logger.warning("[VariantArchive] recording skipped", exc_info=True)


def _maybe_open_diagnostic_entry(
    event: dict[str, Any],
    validation_result: dict[str, Any] | None,
) -> None:
    """P2-7 (round-75): auto-open a diagnostic-ledger entry on cascade
    failures, extracting suspect components from the failing stages' names.
    Same never-raises contract as the variant archive."""
    try:
        stages = []
        if isinstance(validation_result, dict):
            stages = [
                s
                for s in (validation_result.get("results") or [])
                if isinstance(s, dict) and not s.get("ok")
            ]
        suspects = sorted(
            {str(s.get("command", "")).split()[0] for s in stages if s.get("command")}
        )
        symptom = "\n".join(str(s.get("stderr") or s.get("stdout") or "")[-400:] for s in stages)
        if not symptom.strip():
            return
        from evolver.gep.diagnostic_ledger import open_entry

        open_entry(
            run_id=str(event.get("run_id") or ""),
            event_id=str(event.get("id") or ""),
            symptom_text=symptom,
            suspect_components=suspects,
        )
    except Exception:
        logger.warning("[DiagnosticLedger] entry skipped", exc_info=True)


def _append_failure_event(
    last_run: dict[str, Any],
    cwd: Path,
    *,
    blast_radius: dict[str, int],
    error: str,
    score: float = 0.0,
    validation_result: dict[str, Any] | None = None,
    eval_meta: dict[str, Any] | None = None,
    diff_snapshot: str = "",
) -> dict[str, Any] | None:
    """Sprint 24.6 (enable_failure_events): land failed EvolutionEvents on
    rejection paths that historically stayed silent (Node v2 emits failure
    events on every terminal outcome). Flag-off → no event (v1.94.0 parity).
    Returns the event so the caller can persist its scene."""
    if not is_enabled("enable_failure_events"):
        return None
    event = _failure_event(
        last_run,
        last_run.get("mutation", {}),
        blast_radius,
        {"status": "failed", "score": score, "error": error},
        validation_result=validation_result,
        eval_meta=eval_meta,
        diff_snapshot=diff_snapshot,
    )
    append_event_jsonl(event)
    _maybe_record_variant(event, validation_result)
    _maybe_open_diagnostic_entry(event, validation_result)
    return event


# Engine-owned state dirs must not pollute the novelty fingerprint (their
# JSONL contents embed the capsules we compare against), nor be swallowed
# by rollbacks in workspaces that do not gitignore them (E2E calibration:
# stash --include-untracked ate events.jsonl).
_FINGERPRINT_EXCLUDED_DIRS: tuple[str, ...] = (
    ".evolver",
    ".evolver_settings",
    ".evomap",
    ".pytest_cache",
    "logs",
    "memory",
)


def _is_runtime_state(rel: str) -> bool:
    """True for engine runtime-state paths (memory/, .evolver/, .config/...).

    Dogfood round-1 finding (v1.107.0): daemon-churned runtime files were
    committed with the mutation and inflated blast radius (42 files for a
    3-file change). Runtime state is the daemon's own write domain — it never
    belongs to a mutation commit or diff snapshot.
    """
    norm = rel.replace("\\", "/")
    head = norm.split("/", 1)[0]
    return head in _FINGERPRINT_EXCLUDED_DIRS or norm.startswith("evolver/.config/")


def _compute_blast_radius() -> dict[str, int]:
    cwd = get_workspace_root()
    changed = [f for f in git_list_changed_files(cwd) if not _is_runtime_state(f)]
    untracked = [f for f in git_list_untracked_files(cwd) if not _is_runtime_state(f)]
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


def get_fitness_cascade_commands() -> list[dict[str, Any]]:
    """Engine-owned fitness cascade (deep copy; never trusts mutation input).

    S26 promotion: commands whose executable is missing from PATH are skipped
    with a warning so non-Python workspaces degrade to the legacy validation
    path (mutation.validation) instead of failing every cycle. An empty return
    means no cascade stage is runnable here.

    Dogfood round-1 finding (v1.107.0): when evolver runs under a bare venv
    python (no activated environment), ruff/mypy/pytest live next to the
    interpreter — fall back to ``<sys.executable>'s dir`` before skipping.

    Soft-default UX (2026-10-31): adapts commands to project layout via
    validation_probe before checking tool availability.
    """
    from evolver.gep.validation_probe import adapt_cascade_commands

    # First adapt to project layout
    cwd = get_workspace_root()
    adapted, probe_warnings = adapt_cascade_commands(list(FITNESS_CASCADE_COMMANDS), cwd)
    for warning in probe_warnings:
        logger.info("validation probe: %s", warning)

    # Then check tool availability
    bin_dir = Path(sys.executable).parent
    runnable: list[dict[str, Any]] = []
    for spec in adapted:
        argv = list(spec["command"])
        if argv and shutil.which(argv[0]) is None:
            # Probe the interpreter's own bin dir: first by exact name (the
            # POSIX layout), then via which() with an explicit path, which
            # honours PATHEXT on Windows — the tools live there as ruff.exe,
            # so a bare "ruff" filename never matches.
            local = bin_dir / argv[0]
            if not local.is_file():
                local = Path(shutil.which(argv[0], path=str(bin_dir)) or "")
            if local.is_file():
                argv = [str(local), *argv[1:]]
            else:
                logger.warning("fitness cascade skipped: %r not found on PATH", argv[0])
                continue
        runnable.append({**spec, "command": argv})
    return runnable


def _lineage_fields() -> dict[str, Any]:
    """Sprint 22.6 (GEPA ancestry) slot — always empty since the round-121
    P0-4 dead-flag sweep:
    the enable_lineage_lessons dead flag was removed (default-off, no
    schedule), so events carry no parent_event_id until a scheduled feature
    fills this slot."""
    return {}


def _is_disposable_path(rel: str) -> bool:
    """False for engine state dirs and Python cache artifacts."""
    norm = rel.replace("\\", "/")
    head = norm.split("/", 1)[0]
    if head in _FINGERPRINT_EXCLUDED_DIRS:
        return False
    return "__pycache__" not in norm and not norm.endswith(".pyc")


def _disposable_untracked(cwd: Path) -> list[str]:
    """Untracked files a mutation-rollback may delete (engine state spared)."""
    return [f for f in git_list_untracked_files(cwd) if _is_disposable_path(f)]


def _commit_mutation(cwd: Path, label: str) -> bool:
    """Commit an accepted mutation (cascade mode) so later failure rollbacks
    cannot destroy prior accepted-but-uncommitted work (soak round-1 bug:
    one failed solidify disposed every untracked file the loop had ever
    accepted). Stages exactly the changed+disposable-untracked files;
    runtime-state paths (memory/, .evolver/, ...) are never staged — they are
    the daemon's write domain, not part of a mutation."""
    try:
        from evolver.gep.git_ops import run_cmd

        targets = [
            f
            for f in dict.fromkeys(git_list_changed_files(cwd) + _disposable_untracked(cwd))
            if f and not _is_runtime_state(f)
        ]
        if not targets:
            return False
        run_cmd(["add", "--", *targets], cwd=cwd)
        run_cmd(
            ["-c", "commit.gpgsign=false", "commit", "-m", f"evolver: {label}"],
            cwd=cwd,
        )
        return True
    except Exception:
        return False


def _added_from_diff(text: str) -> str:
    """Strictly the ``+`` payload lines of a diff (context lines excluded —
    they dominate tiny diffs and made reversals score ~0.95, soak round 3)."""
    out: list[str] = []
    for line in text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            out.append(line[1:].strip())
    return "".join(out).casefold()


def _novelty_fingerprint(cwd: Path) -> tuple[str, str]:
    """Content fingerprint for the novelty gate: ``(full_text, added_text)``.

    full_text: tracked diff (pathspec-filtered to disposable paths) + untracked
    file contents — a fresh mutation is often entirely untracked, which
    ``git diff HEAD`` misses (Sprint 23 calibration); workspaces that COMMIT
    engine state must not have their own event log pollute the diff (soak r2).

    added_text: the ADDED-content view — strict ``+`` payload lines from the
    diff part, all lines from raw untracked content. Reversals never collide
    with their originals on added-sets (undo's additions = original's
    removals), so the gate stops false-positiving undos (soak r3/r4)."""
    from evolver.gep.git_ops import try_run_cmd

    full_parts: list[str] = []
    added_parts: list[str] = []
    changed = [f for f in git_list_changed_files(cwd) if _is_disposable_path(f)]
    if changed:
        diff = try_run_cmd(["diff", "HEAD", "--", *changed], cwd=cwd)
        full_parts.append(diff)
        added_parts.append(_added_from_diff(diff))
    for rel in git_list_untracked_files(cwd):
        if not _is_disposable_path(rel):
            continue
        try:
            raw = (cwd / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        full_parts.append(raw)
        added_parts.append("".join(ln.strip() for ln in raw.splitlines() if ln.strip()).casefold())
    return "\n".join(full_parts), "".join(added_parts)


def _validate_related_commands(raw_commands: Any) -> tuple[bool, list[list[str]], str]:
    """U-7: Validate that ``related`` scope commands are non-empty argv lists (no bare strings)."""
    if not isinstance(raw_commands, list) or not raw_commands:
        return (
            False,
            [],
            "validation_scope='related' requires a non-empty list of argv lists "
            "(e.g. [['pytest', 'tests/test_x.py']]); empty or non-list input is forbidden.",
        )
    normalized: list[list[str]] = []
    for idx, item in enumerate(raw_commands):
        cmd_val = item.get("command") if isinstance(item, dict) else item
        if not isinstance(cmd_val, list) or not cmd_val:
            return (
                False,
                [],
                f"related command at index {idx} must be a non-empty argv list, "
                f"got {type(cmd_val).__name__}. Bare command strings are forbidden.",
            )
        argv = [str(part) for part in cmd_val]
        head = argv[0].strip()
        if not head or (" " in head and not Path(head).exists()):
            return (
                False,
                [],
                f"related command at index {idx} has spaces in binary name {head!r}; "
                "pass an argv list like ['pytest', 'tests/foo.py'] instead of a shell string.",
            )
        normalized.append(argv)
    return True, normalized, ""


def _classify_env_blockers(
    validation_result: dict[str, Any] | None,
    changed_files: list[str],
) -> list[dict[str, Any]]:
    """U-8: Identify failed validation stages caused by unrelated tests or environment blockers."""
    if not isinstance(validation_result, dict):
        return []
    results = validation_result.get("results") or []
    changed_norm = [f.replace("\\", "/").strip() for f in changed_files if f]
    changed_stems = {Path(f).stem.removeprefix("test_") for f in changed_norm if Path(f).stem}
    blockers: list[dict[str, Any]] = []
    for stage in results:
        if not isinstance(stage, dict) or stage.get("ok"):
            continue
        cmd_str = str(stage.get("command") or "")
        out = f"{stage.get('stdout') or ''}\n{stage.get('stderr') or ''}"

        # 1. File lock / permission blocker
        if any(
            tok in out
            for tok in ("os error 5", "拒绝访问", "Access is denied", "PermissionError", ".lock")
        ):
            blockers.append(
                {
                    "stage": cmd_str[:120],
                    "kind": "env_lock",
                    "unrelated_to_diff": True,
                    "reason": "Environment file lock or permission error detected in stage output.",
                }
            )
            continue

        # 2. Untracked / gitignored doc FileNotFoundError
        fnf_matches = re.findall(r"FileNotFoundError:.*?['\"]([^'\"]+)['\"]", out)
        if fnf_matches and all(
            not any(cf in m.replace("\\", "/") for cf in changed_norm) for m in fnf_matches
        ):
            blockers.append(
                {
                    "stage": cmd_str[:120],
                    "kind": "missing_untracked_file",
                    "unrelated_to_diff": True,
                    "files": fnf_matches[:10],
                    "reason": (
                        "Stage failed due to missing untracked/ignored file not touched by diff."
                    ),
                }
            )
            continue

        # 3. Pytest failures in files unrelated to changed_files
        failed_nodes = re.findall(r"^(?:FAILED|ERROR)\s+([^\s:]+(?:\.py))", out, flags=re.MULTILINE)
        if failed_nodes:
            unrelated_nodes: list[str] = []
            related_nodes: list[str] = []
            for node_file in dict.fromkeys(failed_nodes):
                nf_norm = node_file.replace("\\", "/").strip()
                nf_stem = Path(nf_norm).stem.removeprefix("test_")
                is_rel = any(
                    nf_norm == cf
                    or nf_norm.endswith("/" + cf)
                    or cf.endswith("/" + nf_norm)
                    or (nf_stem and nf_stem in changed_stems)
                    for cf in changed_norm
                )
                if is_rel:
                    related_nodes.append(nf_norm)
                else:
                    unrelated_nodes.append(nf_norm)
            if unrelated_nodes and not related_nodes:
                blockers.append(
                    {
                        "stage": cmd_str[:120],
                        "kind": "unrelated_test_failure",
                        "unrelated_to_diff": True,
                        "files": unrelated_nodes[:20],
                        "reason": (
                            f"All failing test files ({', '.join(unrelated_nodes[:5])}) "
                            "are outside the current mutation's changed files."
                        ),
                    }
                )
    return blockers


def _is_hard_block_mutation(mutation: dict[str, Any], cwd: Path) -> tuple[bool, str | None]:
    """Check if mutation is a hard block (secrets or protected state paths).

    Returns (is_hard_block, reason).
    Only hard blocks: secrets, mutations targeting state_root/~/.evolver.
    Everything else is soft-continue.

    Soft-default UX (2026-10-31 spec).
    """
    from evolver.gep.paths import get_evolver_state_root

    # Check for secrets via policy check
    try:
        from evolver.gep.policy_check import check_policy

        # Get diff for secret checking
        diff_text = capture_diff_snapshot(cwd)
        policy_report = check_policy(diff_text=diff_text)

        if not policy_report.ok:
            # Look for secret violations
            for violation in policy_report.violations:
                if violation.rule == "secret_leak" and violation.severity == "critical":
                    return True, f"secret_leak: {violation.message}"
    except Exception:
        logger.warning("Policy check failed during hard-block detection", exc_info=True)

    # Check for protected state paths
    try:
        state_root = get_evolver_state_root()
        state_root_str = str(state_root.resolve())

        changes = mutation.get("changes", [])
        for change in changes:
            file_path = change.get("file", "")
            if not file_path:
                continue

            # Resolve to absolute path
            abs_path = (cwd / file_path).resolve()
            abs_str = str(abs_path)

            # Check if touching state_root or ~/.evolver
            if abs_str.startswith(state_root_str):
                return True, f"protected_state: {file_path} targets state_root"

            # Check for explicit do_not_touch patterns
            if ".evolver/" in file_path or "memory/" in file_path:
                # These might be legacy paths that should be protected
                if not file_path.startswith("src/") and not file_path.startswith("tests/"):
                    return True, f"protected_state: {file_path} targets engine state"
    except Exception:
        logger.warning("Protected path check failed during hard-block detection", exc_info=True)

    return False, None


def _handle_cascade_validation_failure(
    *,
    last_run: dict[str, Any],
    mutation: dict[str, Any],
    cwd: Path,
    validation_result: dict[str, Any],
    validation_report: dict[str, Any] | None,
    eval_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Workbench-draft split (算子即基因 v1.114.0, 支柱一): validation failure
    is an honest ``ok=False, outcome="draft_preserved"``.

    The patch stays in place (backed up to ``rejected_stashes/<run_id>`` first
    so nothing can be lost), the caller must NOT proceed to the vault path,
    and the return carries a 3-line human ``actionable_fix`` with file:line
    precision. Only hard blocks (secrets, protected state) roll the tree back.
    """
    score = _cascade_score(validation_result["results"])

    # Check for hard blocks (secrets or protected state)
    is_hard_block, block_reason = _is_hard_block_mutation(mutation, cwd)

    if is_hard_block:
        # Hard block: rollback and reject as before
        diff_snapshot = _failure_diff(cwd)
        failed_blast = _compute_blast_radius()
        failed_fp, failed_added = _novelty_fingerprint(cwd)
        changed_now = [
            f
            for f in git_list_changed_files(cwd) + _disposable_untracked(cwd)
            if f and not _is_runtime_state(f)
        ]
        env_blockers = _classify_env_blockers(validation_result, changed_now)
        stash_info = snapshot_rejected_worktree(
            cwd,
            run_id=str(last_run.get("run_id") or ""),
            disposable_untracked=_disposable_untracked(cwd),
            reason="hard_block_validation",
        )
        rollback_tracked(cwd=cwd, include_untracked=False)
        rollback_new_untracked_files(_disposable_untracked(cwd), cwd=cwd)
        event = _failure_event(
            last_run,
            mutation,
            failed_blast,
            {
                "status": "failed",
                "score": score,
                "error": "hard_block_validation",
                "block_reason": block_reason,
            },
            validation_result=validation_result,
            eval_meta=eval_meta,
            novelty_fingerprint=failed_fp[:4000],
            novelty_added=failed_added[:4000],
            diff_snapshot=diff_snapshot,
        )
        append_event_jsonl(event)
        record_solidify_failure(last_run, error="hard_block_validation", score=score)
        _wiki_rejection("hard_block_validation", last_run, score=score)
        event_id = _remember_failure_scene(event, validation_result=validation_result)
        details = dict(validation_result)
        details["score"] = score
        details["stash"] = stash_info
        details["env_blockers"] = env_blockers
        details["env_blocker_only"] = bool(env_blockers)
        if validation_report is not None:
            details["validation_report"] = validation_report
        return {
            "ok": False,
            "outcome": "hard_veto_rolled_back",
            "error": "hard_block_validation",
            "block_reason": block_reason,
            "event_id": event_id,
            "stash": stash_info,
            "rejected_stash": stash_info,
            "env_blockers": env_blockers,
            "env_blocker_only": bool(env_blockers),
            "details": details,
        }

    # Draft-preserved path (支柱一): capture failure details, keep the patch.
    warnings: list[str] = []
    for i, result in enumerate(validation_result.get("results", [])):
        if not result.get("ok"):
            cmd = result.get("command", f"stage_{i}")
            stderr = result.get("stderr", "")
            warnings.append(f"Validation failed: {cmd}")
            if stderr:
                # Truncate stderr for warning
                stderr_brief = stderr[:200] + "..." if len(stderr) > 200 else stderr
                warnings.append(f"  {stderr_brief}")

    # Record the failure honestly: failure-side event, repair-loop signal,
    # variant archive — but strictly zero positive vault assets.
    run_id = str(last_run.get("run_id") or "")
    stash_info = snapshot_rejected_worktree(
        cwd,
        run_id=run_id,
        disposable_untracked=_disposable_untracked(cwd),
        reason="draft_preserved_validation",
    )
    _retract_this_runs_distilled_assets(run_id)
    diff_snapshot = _failure_diff(cwd)
    failed_blast = _compute_blast_radius()
    failed_fp, failed_added = _novelty_fingerprint(cwd)

    event = _failure_event(
        last_run,
        mutation,
        failed_blast,
        {"status": "failed", "score": score, "error": "validation_failed"},
        validation_result=validation_result,
        eval_meta=eval_meta,
        novelty_fingerprint=failed_fp[:4000],
        novelty_added=failed_added[:4000],
        diff_snapshot=diff_snapshot,
    )
    append_event_jsonl(event)
    record_solidify_failure(last_run, error="validation_failed", score=score)
    _wiki_rejection("validation_failed", last_run, score=score)
    _maybe_record_variant(event, validation_result)
    event_id = _remember_failure_scene(event, validation_result=validation_result)

    details = dict(validation_result)
    details["score"] = score
    details["stash"] = stash_info
    details["rejected_stash"] = stash_info
    if validation_report is not None:
        details["validation_report"] = validation_report

    return {
        "ok": False,
        "outcome": "draft_preserved",
        "error": "validation_failed",
        "event_id": event_id,
        "score": score,
        "warnings": warnings,
        "actionable_fix": _actionable_fix_from_validation(validation_result, run_id),
        "validation_timing": event.get("validation_timing"),
        "stash": stash_info,
        "rejected_stash": stash_info,
        "details": details,
    }


#: Cycle outcomes that are process states, not Candidate verdicts. They must
#: not land in the paired session as Rejects and must not clear a stale gate
#: record — there was no Candidate being judged.
_PROCESS_STATES: Final[frozenset[str]] = frozenset(
    {
        "no_pending_run",
        "already_solidified",
        "not_a_git_repo",
        "skip_validation_requires_pending_run",
    }
)


def _pending_cycle_context() -> tuple[dict[str, Any], str]:
    """The pending swarm cycle's id/candidate, plus the declared hypothesis
    text — both read BEFORE the cycle burns them (§5.3 用后即焚)."""
    pending_run: dict[str, Any] = {}
    try:
        state = _read_solidify_state() or {}
        raw = state.get("last_run")
        if isinstance(raw, dict):
            pending_run = dict(raw)
    except Exception:
        pending_run = {}
    text = ""
    try:
        from evolver.gep.hypothesis import load_hypothesis

        record = load_hypothesis()
        if isinstance(record, dict):
            text = str(record.get("hypothesis") or "")
    except Exception:
        text = ""
    return pending_run, text


def _pending_candidate_id(pending_run: dict[str, Any] | None) -> str:
    """The candidate this cycle is trying to land — the mutation id when the
    state carries one, the selected gene otherwise."""
    run = pending_run if isinstance(pending_run, dict) else {}
    mutation = run.get("mutation")
    mutation = mutation if isinstance(mutation, dict) else {}
    return str(mutation.get("id") or run.get("selected_gene_id") or "")


def _session_round_scopes() -> tuple[str, ...]:
    """Round scopes that count as "this round" beside the swarm cycle id:
    the running paired session's own id.

    ``evolver session hypothesize`` stamps its records with the session id,
    the host stamps the cycle id — both are this round. A leftover record
    from a previous cycle matches neither and stays refused.
    """
    try:
        from evolver.gep.evolution_session import RUNNING, EvolutionSession

        run = EvolutionSession().latest_run()
    except Exception:
        return ()
    if isinstance(run, dict) and run.get("status") == RUNNING and run.get("run_id"):
        return (str(run["run_id"]),)
    return ()


def _settle_session(
    result: dict[str, Any],
    *,
    pending_run: dict[str, Any] | None = None,
    hypothesis: str = "",
) -> dict[str, Any] | None:
    """配对会话 §5.1/§5.2 — fold this cycle into the paired session ledger.

    A refusal is a Reject: the session stays ``running`` and ``rounds.jsonl``
    remembers why, so the engine cannot publish later as if nothing had
    happened. A publish leaves an ``accept: true`` gate decision so the
    session's Accept is an echo of a real gate verdict, never a bare claim.
    Process states (nothing pending, already solidified, a HITL wait) are not
    Candidate verdicts and touch nothing. Bookkeeping must never turn a
    measured rejection into a crash, so every failure here is swallowed with
    a warning.

    The fold OPENS the round first (:meth:`EvolutionSession.begin_round`).
    Without it ``current_candidate`` stayed empty forever, ``session accept``
    refused with "no Candidate", and the frozen budget never moved — a gate
    that judged nobody (round-86 seam). The cycle id keys the idempotence:
    one Candidate, one round, however many times solidify retries.
    """
    if not isinstance(result, dict):
        return None
    ok = result.get("ok") is True
    error = "" if ok else str(result.get("error") or "")
    if not ok:
        if not error or error in _PROCESS_STATES or error.startswith(("hitl_", "supervision_")):
            return None

    session = _session_active()
    if session is None:
        # No running session — nothing to fold into; the verdict stands as-is.
        return None

    cycle_ref = str((pending_run or {}).get("run_id") or "")
    if cycle_ref and session.has_round_for(cycle_ref):
        # A retried solidify of the same pending run already spent its round.
        return None

    try:
        candidate = _pending_candidate_id(pending_run) or cycle_ref or "unknown-candidate"
        session.begin_round(hypothesis, candidate)
    except Exception:
        # Budget exhaustion closes the session itself (incomplete); anything
        # else leaves the ledger untouched. Either way the verdict returned
        # to the caller is unchanged — bookkeeping must not rewrite it.
        logger.warning("[session] round not opened — ledger untouched", exc_info=True)
        return None

    if ok:
        bench = result.get("bench_pack") if isinstance(result.get("bench_pack"), dict) else {}
        soft = bool(result.get("soft_accept") or (bench or {}).get("soft_accept"))
        gate_rec: dict[str, Any] = {
            "accept": True,
            "reason": "soft_accept" if soft else "solidify_published",
            "score": result.get("score"),
            "bench_pack": result.get("bench_pack"),
        }
        if soft:
            gate_rec["soft_accept"] = True
            gate_rec["soft_reason"] = (bench or {}).get("soft_reason") or (bench or {}).get(
                "reason"
            )
            gate_rec["warnings"] = list(
                result.get("warnings") or (bench or {}).get("warnings") or []
            )
            if result.get("next_steps") or (bench or {}).get("next_steps"):
                gate_rec["next_steps"] = list(
                    result.get("next_steps") or (bench or {}).get("next_steps") or []
                )
        _session_gate_record(gate_rec)
        return None

    _session_gate_record({"accept": False, "reason": error})
    return _session_reject(error, result, cycle_ref=cycle_ref)


def _session_active() -> Any | None:
    """The running paired session, or ``None`` when there is none to update."""
    from evolver.gep.evolution_session import RUNNING, EvolutionSession

    session = EvolutionSession()
    try:
        run = session.latest_run()
    except Exception:
        return None
    if not isinstance(run, dict) or run.get("status") != RUNNING:
        return None
    try:
        session.resume()
    except Exception:
        return None
    return session


def _session_gate_record(decision: dict[str, Any]) -> None:
    """Persist the latest gate decision on the running session (best effort)."""
    try:
        session = _session_active()
        if session is None:
            return
        session.record_gate_decision(decision)
    except Exception:
        logger.warning("[session] gate decision not recorded", exc_info=True)


def _session_reject(
    error: str,
    result: dict[str, Any],
    *,
    cycle_ref: str = "",
) -> dict[str, Any] | None:
    """Write the refusal into ``rounds.jsonl``; the session stays running."""
    try:
        session = _session_active()
        if session is None:
            return None
        raw_details = result.get("details")
        details = raw_details if isinstance(raw_details, dict) else {}
        raw_bench = details.get("bench_pack")
        bench = raw_bench if isinstance(raw_bench, dict) else {}
        metrics: dict[str, Any] = {}
        if bench:
            metrics = {
                "bench_pack_score": bench.get("score"),
                "bench_pack_reason": bench.get("reason"),
            }
        entry = session.record_round(
            decision="reject", notes=error, metrics=metrics, cycle_ref=cycle_ref
        )
        run = session.run
        return {
            "run_id": run.get("run_id"),
            "round": entry.get("round"),
            "rejects": session.rejected_count(),
            "budget_max_rounds": (run.get("budget") or {}).get("max_rounds"),
            "status": session.status,
        }
    except Exception:
        logger.warning("[session] reject not recorded — session untouched", exc_info=True)
        return None


def solidify(
    *,
    mutation_override: dict[str, Any] | None = None,
    skip_validation: bool = False,
    proposal: dict[str, Any] | Path | str | None = None,
    validation_scope: str | None = None,
    related_commands: list[list[str]] | None = None,
    restore_stash: bool = False,
) -> dict[str, Any]:
    """Run a solidify cycle, then fold the outcome into the paired session.

    The session ledger is updated here — once, on the way out — rather than
    at every internal refusal point: one funnel, so no refusal path can
    quietly skip the bookkeeping (round-84 lesson: the gate was built, the
    writer was not wired).
    """
    if restore_stash:
        target_cwd = get_repo_root(_quiet=True) or get_workspace_root()
        return restore_rejected_stash(cwd=target_cwd)

    # The cycle context is read BEFORE _solidify_cycle consumes it: the
    # ledger needs the cycle id and the candidate id, and the hypothesis
    # file is burned on acceptance (§5.3 + U-5), so its text is read
    # here while it still exists.
    pending_run, hypothesis_text = _pending_cycle_context()
    result = _solidify_cycle(
        mutation_override=mutation_override,
        skip_validation=skip_validation,
        proposal=proposal,
        validation_scope=validation_scope,
        related_commands=related_commands,
    )
    run_id_str = str(pending_run.get("run_id") or "")
    if isinstance(result, dict) and result.get("ok") is not True:
        err_now = str(result.get("error") or "")
        if run_id_str and err_now not in _PROCESS_STATES:
            _retract_this_runs_distilled_assets(run_id_str)
        if result.get("event_id"):
            # 回放即裁决: a judged failure is still a settle — the round closed
            # with its failure episode, so consume the pending run.
            _mark_run_settled(run_id_str, err_now)
    # U-5: Hypothesis shares fate with commit — only consume on solidify.ok == True;
    # preserve on failure so the host does not need to re-declare on retry.
    try:
        from evolver.gep.hypothesis import consume_hypothesis, preserve_hypothesis_on_failure

        if isinstance(result, dict):
            if result.get("ok") is True and result.get("action") != "no_action":
                consume_hypothesis(run_id_str)
            elif result.get("ok") is False:
                err_code = str(result.get("error") or "")
                if (
                    err_code
                    and err_code not in _PROCESS_STATES
                    and err_code != "hypothesis_missing"
                ):
                    preserve_hypothesis_on_failure(run_id_str)
    except Exception:
        logger.warning("[hypothesis] post-cycle fate sync failed", exc_info=True)

    try:
        session_state = _settle_session(result, pending_run=pending_run, hypothesis=hypothesis_text)
    except Exception:
        logger.warning("[session] settle failed — result returned as-is", exc_info=True)
        session_state = None
    if session_state is not None and isinstance(result, dict):
        result = {**result, "session": session_state}
    return result


def _solidify_cycle(
    *,
    mutation_override: dict[str, Any] | None = None,
    skip_validation: bool = False,
    proposal: dict[str, Any] | Path | str | None = None,
    validation_scope: str | None = None,
    related_commands: list[list[str]] | None = None,
) -> dict[str, Any]:
    """Run a solidify cycle (the gates; session bookkeeping lives above)."""
    state = _read_solidify_state()
    if not state or not state.get("last_run"):
        return {"ok": False, "error": "no_pending_run"}

    last_run = state["last_run"]
    cwd = get_workspace_root()

    proposal_report: dict[str, Any] | None = None
    if proposal is not None:
        from evolver.gep.proposal import apply_proposal, compose_proposals, parse_proposal

        try:
            if isinstance(proposal, (str, Path)):
                raw_proposal = Path(proposal).read_text(encoding="utf-8")
            else:
                raw_proposal = json.dumps(proposal, ensure_ascii=False, default=str)
        except Exception as exc:
            return {
                "ok": False,
                "error": "proposal_rejected",
                "message": str(exc),
            }

        # 配对会话 §5.2: the proposal round is design context. A proposal that
        # carries val wording or expected answers is refused outright — the
        # whole document is suspect, not just the offending line.
        try:
            from evolver.gep.val_seal import ValSealBreachError, assert_sealed

            assert_sealed(raw_proposal, where="proposal_round")
        except ValSealBreachError as exc:
            return {
                "ok": False,
                "error": "val_seal_breach",
                "failure_mode": {"mode": "soft", "reasonClass": "val_seal", "retryable": True},
                "next_action": "evolve_begin",
                "details": {"val_seal": {"where": "proposal_round", "detail": str(exc)}},
            }

        try:
            raw_obj = json.loads(raw_proposal) if isinstance(proposal, (str, Path)) else proposal
            if isinstance(raw_obj, dict) and isinstance(raw_obj.get("candidates"), list):
                composed = compose_proposals(
                    raw_obj["candidates"],
                    root=cwd,
                    apply=True,
                    gene_id=str(raw_obj.get("gene_id") or "") or None,
                )
                comp_prop = composed.get("proposal")
                action_str = (
                    str(comp_prop.get("action") or "no_action")
                    if isinstance(comp_prop, dict)
                    else str(getattr(comp_prop, "action", None) or "no_action")
                )
                apply_rep = composed.get("apply_report")
                proposal_report = dict(apply_rep) if isinstance(apply_rep, dict) else {}
                proposal_report["decision"] = composed.get("decision")
                proposal_report["composition_ledger"] = composed.get("composition_ledger", [])
            else:
                parsed_p = parse_proposal(raw_obj)
                proposal_report = apply_proposal(parsed_p, cwd)
                action_str = parsed_p.action
        except Exception as exc:
            return {
                "ok": False,
                "error": "proposal_rejected",
                "message": str(exc),
            }
        if action_str == "no_action":
            return {
                "ok": True,
                "action": "no_action",
                "files_changed": [],
                "proposal": proposal_report,
            }

    # Duplicate-solidify guard (round-12): a re-run on an already-landed run
    # used to burn a full validation cascade (~7 min), succeed with nothing to
    # commit, and append a phantom success event — inflating the acceptance
    # gate's soak sample with a run that validated no mutation.
    last_solidify = state.get("last_solidify") or {}
    run_id_str = str(last_run.get("run_id") or "")
    # Round-121 review: a FAILED settle is retryable — the host fixes the
    # tree and re-runs solidify on the same pending run. Only a landed
    # (successful) run is guarded against double-settling.
    if (
        run_id_str
        and last_solidify.get("run_id") == run_id_str
        and last_solidify.get("outcome") != "failed"
    ):
        return {
            "ok": False,
            "error": "already_solidified",
            "run_id": run_id_str,
            "next_action": "evolve_begin",
        }

    from evolver.gep import supervision as supervision_mod

    if supervision_mod.is_paused():
        return {"ok": False, "error": "supervision_paused"}
    gene_id = str(last_run.get("selected_gene_id") or "")
    landed_head = ""
    raw_landed = last_run.get("landed_gene_ids") or []
    if isinstance(raw_landed, list) and raw_landed:
        landed_head = str(raw_landed[0])
    veto = supervision_mod.check_veto(
        f"solidify:{last_run.get('run_id') or ''}",
        str(last_run.get("run_id") or ""),
        gene_id,
        landed_head,
    )
    if veto is not None:
        return {"ok": False, "error": "supervision_veto", "veto": veto}

    raw_scope = (
        validation_scope
        or last_run.get("validation_scope")
        or (last_run.get("mutation") or {}).get("validation_scope")
    )
    scope_mode = str(raw_scope).strip().lower() if raw_scope else ""
    if scope_mode == "skip":
        skip_validation = True

    if skip_validation:
        run_id = last_run.get("run_id") or (last_run.get("mutation") or {}).get("id")
        if not run_id or str(run_id) == "unknown":
            return {"ok": False, "error": "skip_validation_requires_pending_run"}
        from evolver.gep import hitl as hitl_mod

        approval = hitl_mod.request_approval(
            subject=f"solidify_skip_validation:{run_id}",
            risk_reason="solidify(skip_validation=True) bypasses the validation cascade",
            requested_by="solidify",
        )
        if approval.get("status") != "approved":
            return {
                "ok": False,
                "error": f"hitl_{approval.get('status', 'pending')}",
                "approval": approval,
            }

    # Soft-default UX (2026-10-31): no-git-repo is soft-continue
    no_git_repo = False
    no_git_warnings: list[str] = []
    if not is_git_repo(cwd):
        fallback_repo = get_repo_root(cwd, _quiet=True)
        if fallback_repo is not None and is_git_repo(fallback_repo):
            cwd = fallback_repo
        else:
            # Soft-continue: warn but still write experience
            no_git_repo = True
            candidates = discover_git_candidates(cwd)
            no_git_warnings.append(
                f"No git repository found at {cwd}. Experience will still be written to state_root."
            )
            if candidates:
                no_git_warnings.append(
                    f"Found git repositories in subdirectories: {candidates}. "
                    "Consider setting EVOLVER_REPO_ROOT to target one."
                )
            else:
                no_git_warnings.append(
                    f"Run 'git init {cwd}' or set EVOLVER_REPO_ROOT to initialize git."
                )
            # Continue to write experience despite no git repo

    mutation = _annotate_mutation_lineage(
        last_run, mutation_override or last_run.get("mutation", {})
    )
    resolved_tier = ""
    resolved_scope_label = scope_mode or "default"
    changed_for_plan: list[str] = []
    if not no_git_repo:
        changed_for_plan = [
            f
            for f in dict.fromkeys(git_list_changed_files(cwd) + _disposable_untracked(cwd))
            if f and not _is_runtime_state(f)
        ]

    # U-7 + P1-3 validation_scope ("auto" | "lightning" | "related" | "cascade" | "skip")
    if scope_mode == "related" and not skip_validation:
        raw_rel = (
            related_commands
            if related_commands is not None
            else (
                last_run.get("related_commands")
                or mutation.get("related_commands")
                or mutation.get("validation")
            )
        )
        valid_rel, normalized_rel, rel_err = _validate_related_commands(raw_rel)
        if not valid_rel:
            return {
                "ok": False,
                "error": "invalid_related_command_format",
                "message": rel_err,
                "failure_mode": {
                    "mode": "soft",
                    "reasonClass": "validation_scope",
                    "retryable": True,
                },
                "next_action": "evolve_settle",
            }
        cascade_mode = is_enabled("enable_fitness_cascade")
        validation_commands: list[Any] = normalized_rel
        resolved_scope_label = "related"
    elif scope_mode == "cascade" and not skip_validation:
        cascade_mode = True
        validation_commands = get_fitness_cascade_commands()
        resolved_tier = "L2"
        resolved_scope_label = "cascade"
    elif (
        not skip_validation
        and not no_git_repo
        and (
            scope_mode in ("auto", "lightning")
            or (
                scope_mode == ""
                and is_enabled("enable_fitness_cascade")
                and FITNESS_CASCADE_COMMANDS is _CONFIG_FITNESS_CASCADE_COMMANDS
            )
        )
    ):
        from evolver.gep.import_graph import select_validation_plan

        plan = select_validation_plan(cwd, changed_for_plan)
        cascade_mode = True
        if plan.tier == "L2":
            resolved_tier = "L2"
            resolved_scope_label = "cascade"
            validation_commands = get_fitness_cascade_commands()
        else:
            resolved_tier = "L0"
            resolved_scope_label = "lightning"
            validation_commands = plan.commands
    else:
        # Sprint 22.2 (enable_fitness_cascade): the validation set is engine-owned
        # (config FITNESS_CASCADE_COMMANDS). mutation.validation comes from
        # external LLM output (distill) and is never executed in this mode.
        cascade_mode = is_enabled("enable_fitness_cascade") and not skip_validation
        if cascade_mode:
            validation_commands = get_fitness_cascade_commands()
            resolved_tier = "L2"
            resolved_scope_label = "cascade"
        else:
            validation_commands = mutation.get("validation") or []

    # 配对会话 §5.3 — one Candidate validates one primary hypothesis. Checked
    # BEFORE the val gate (and before paying for the cascade): no record, no
    # measurement, no publish. The record must belong to THIS round when it
    # carries a run_id; U-5 stages it here for boundary episode recording and
    # only consumes (deletes) it when solidify succeeds (ok == True).
    declared_hypothesis: dict[str, Any] | None = None
    try:
        from evolver.gep.hypothesis import (
            HypothesisError,
            load_hypothesis,
            require_for_gate,
            stage_hypothesis,
        )

        # The record is staged below (and consumed on solidify.ok == True),
        # while the floors it declared outlive it so the pack gate asserts them.
        declared_hypothesis = load_hypothesis()
        require_for_gate(
            declared_hypothesis,
            run_id=last_run.get("run_id"),
            also_accept=_session_round_scopes(),
        )
    except HypothesisError as exc:
        return _hypothesis_rejection(last_run, cwd, str(exc))
    except Exception:
        logger.warning("[hypothesis-gate] record unusable — rejecting", exc_info=True)
        return _hypothesis_rejection(last_run, cwd, "hypothesis record unreadable")
    else:
        stage_hypothesis(str(last_run.get("run_id") or ""))

    validation_result: dict[str, Any] | None = None
    validation_report: dict[str, Any] | None = None
    # RSI P0-1 (anchor evaluation): a mutation touching the verification
    # machinery must survive the out-of-tree frozen contracts. In-repo tests
    # are mutable by the very mutation they judge — without the anchor, a
    # change that weakens the gate and its tests together would be accepted
    # by the weakened gate (self-preferencing loop, RSI演进对照.md P0-1).
    # Runs even on the skip-validation path (cheap, human already approved
    # the skip; the anchor guards against weakening the guards themselves).
    anchor_result: dict[str, Any] | None = None
    from evolver.gep.eval_worktree import isolated_eval_cwd

    with isolated_eval_cwd(cwd) as (eval_cwd, eval_meta):
        if not skip_validation and validation_commands:
            validation_result = _run_validations(
                validation_commands, eval_cwd, cascade=cascade_mode
            )
            if resolved_tier:
                validation_result["tier"] = resolved_tier
            if resolved_scope_label:
                validation_result["scope"] = resolved_scope_label
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
                if cascade_mode:
                    # 支柱一: a red validation is a workbench draft
                    # (ok=False, outcome=draft_preserved) or a hard block —
                    # either way the vault path stays unreachable.
                    return _handle_cascade_validation_failure(
                        last_run=last_run,
                        mutation=mutation,
                        cwd=cwd,
                        validation_result=validation_result,
                        validation_report=validation_report,
                        eval_meta=eval_meta,
                    )
                # Legacy non-cascade path: same draft contract, minus cascade
                # extras. Blast radius and diff must be captured BEFORE any
                # state change (Sprint 23 lesson — after rollback the tree is
                # clean).
                failed_blast = _compute_blast_radius()
                diff_snapshot = _failure_diff(cwd)
                changed_now = [
                    f
                    for f in git_list_changed_files(cwd) + _disposable_untracked(cwd)
                    if f and not _is_runtime_state(f)
                ]
                env_blockers = _classify_env_blockers(validation_result, changed_now)
                is_hard_block, block_reason = _is_hard_block_mutation(mutation, cwd)
                stash_info = snapshot_rejected_worktree(
                    cwd,
                    run_id=str(last_run.get("run_id") or ""),
                    disposable_untracked=_disposable_untracked(cwd),
                    reason="hard_block_validation" if is_hard_block else "validation_failed",
                )
                if is_hard_block:
                    rollback_tracked(cwd=cwd, include_untracked=False)
                    rollback_new_untracked_files(_disposable_untracked(cwd), cwd=cwd)
                err_tag = "hard_block_validation" if is_hard_block else "validation_failed"
                record_solidify_failure(last_run, error=err_tag)
                failed_event = _append_failure_event(
                    last_run,
                    cwd,
                    blast_radius=failed_blast,
                    error=err_tag,
                    validation_result=validation_result,
                    eval_meta=eval_meta,
                    diff_snapshot=diff_snapshot,
                )
                details: dict[str, Any] = dict(validation_result)
                details["stash"] = stash_info
                details["env_blockers"] = env_blockers
                details["env_blocker_only"] = bool(env_blockers)
                if validation_report is not None:
                    details["validation_report"] = validation_report
                legacy_result: dict[str, Any] = {
                    "ok": False,
                    "outcome": "hard_veto_rolled_back" if is_hard_block else "draft_preserved",
                    "error": err_tag,
                    "stash": stash_info,
                    "env_blockers": env_blockers,
                    "env_blocker_only": bool(env_blockers),
                    "details": details,
                }
                if is_hard_block:
                    legacy_result["block_reason"] = block_reason
                else:
                    legacy_result["actionable_fix"] = _actionable_fix_from_validation(
                        validation_result, str(last_run.get("run_id") or "")
                    )
                if failed_event is not None:
                    legacy_result["event_id"] = _remember_failure_scene(
                        failed_event, validation_result=validation_result
                    )
                return legacy_result

        # Strategist S-8b: Anti-cheat fig-leaf static gate — reject test-skipping,
        # deleted tests, or hardcoded task/benchmark literals before promotion.
        if not skip_validation and not no_git_repo:
            from evolver.gep.policy_check import detect_anti_cheat_violations

            anti_cheat_diff = capture_diff_snapshot(cwd, max_chars=32_000)
            anti_cheat_hits = detect_anti_cheat_violations(
                cwd,
                changed_for_plan,
                diff_text=anti_cheat_diff,
            )
            critical_cheats = [v for v in anti_cheat_hits if v.severity == "critical"]
            if critical_cheats:
                failed_blast = _compute_blast_radius()
                diff_snapshot = _failure_diff(cwd)
                run_id_ac = str(last_run.get("run_id") or "")
                stash_info = snapshot_rejected_worktree(
                    cwd,
                    run_id=run_id_ac,
                    disposable_untracked=_disposable_untracked(cwd),
                    reason="anti_cheat_violation",
                )
                _retract_this_runs_distilled_assets(run_id_ac)
                record_solidify_failure(last_run, error="anti_cheat_violation", score=0.0)
                _wiki_rejection("anti_cheat_violation", last_run, score=0.0)
                ac_event = _append_failure_event(
                    last_run,
                    cwd,
                    blast_radius=failed_blast,
                    error="anti_cheat_violation",
                    validation_result=validation_result,
                    eval_meta=eval_meta,
                    diff_snapshot=diff_snapshot,
                )
                ac_out: dict[str, Any] = {
                    "ok": False,
                    "outcome": "draft_preserved",
                    "error": "anti_cheat_violation",
                    "stash": stash_info,
                    "actionable_fix": [
                        critical_cheats[0].message[:140],
                        (
                            "Restore real assertions or fix root cause without "
                            "hardcoding/skipping tests."
                        ),
                        _workbench_preserved_line(run_id_ac),
                    ],
                    "failure_mode": {
                        "mode": "soft",
                        "reasonClass": "anti_cheat",
                        "retryable": True,
                    },
                    "next_action": "evolve_begin",
                    "details": {
                        "anti_cheat_violations": [
                            {"rule": v.rule, "severity": v.severity, "message": v.message}
                            for v in critical_cheats
                        ]
                    },
                }
                if ac_event is not None:
                    ac_out["event_id"] = _remember_failure_scene(
                        ac_event, validation_result=validation_result
                    )
                if run_id_ac and ac_out.get("event_id"):
                    _mark_run_settled(run_id_ac, "anti_cheat_violation")
                return ac_out

        # RSI P0-1: anchor contracts for verifier-surface mutations.
        anchor_touched = touches_verifier_surface(
            [
                f
                for f in git_list_changed_files(cwd) + git_list_untracked_files(cwd)
                if f and not _is_runtime_state(f)
            ]
        )
        if anchor_touched:
            anchor_result = run_anchor_suite()
            if not anchor_result["ok"]:
                diff_snapshot = _failure_diff(cwd)
                failed_blast = _compute_blast_radius()
                rollback_tracked(cwd=cwd, include_untracked=False)
                rollback_new_untracked_files(_disposable_untracked(cwd), cwd=cwd)
                anchor_event = _failure_event(
                    last_run,
                    mutation,
                    failed_blast,
                    {"status": "failed", "score": 0.0, "error": "anchor_failed"},
                    validation_result=validation_result,
                    eval_meta=eval_meta,
                    diff_snapshot=diff_snapshot,
                )
                append_event_jsonl(anchor_event)
                _maybe_record_variant(anchor_event, validation_result)
                record_solidify_failure(last_run, error="anchor_failed", score=0.0)
                return {
                    "ok": False,
                    "error": "anchor_failed",
                    "event_id": _remember_failure_scene(
                        anchor_event, validation_result=validation_result
                    ),
                    "failure_mode": {
                        "mode": "hard",
                        "reasonClass": "anchor",
                        "retryable": False,
                    },
                    "next_action": "stop_and_report",
                    "details": {"touched": anchor_touched, "anchor_result": anchor_result},
                }

        # Self-Harness A1: empirical acceptance gate. S26.5 runs it in the
        # isolated eval tree when the flag is on (fallback = live cwd).
        # P1-3: L0 lightning validation targets impacted tests only (<3s budget);
        # running the full-repo T0 suite inline would defeat L0 leaf isolation.
        gate_result = None if resolved_tier == "L0" else gate_or_none(last_run, eval_cwd)
    if (
        rejected := _apply_acceptance_gate(
            gate_result, last_run, cwd, validation_result=validation_result
        )
    ) is not None:
        return rejected

    # Charter 外部适应度: frozen bench pack — an enforced fitness floor.
    pack_rejection, bench_pack_verdict = _apply_bench_pack_gate(
        last_run,
        cwd,
        validation_result=validation_result,
        declaration=declared_hypothesis,
    )
    if pack_rejection is not None:
        return pack_rejection

    blast_radius = _compute_blast_radius()
    diff_snapshot = capture_diff_snapshot(cwd, max_chars=_STORED_DIFF_CHARS)

    # S26.3 fitness ledger: record the measured verdict on the event, never
    # reject on it (round-121 review: _cascade_score saturates at 1.0 — it is
    # a validation floor, not a fitness measure; rejecting on it would lock
    # out every all-green round after the first). The frozen val pack gate is
    # the fitness ruler; it rejects non-improvements on its own verdict.
    outcome_score: float | None = (
        _cascade_score(validation_result["results"]) if validation_result else None
    )
    fitness_verdict = record_measurement(
        outcome_score, source=f"solidify:{last_run.get('run_id') or 'unknown'}"
    )

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
        "timestamp": _now_iso_ms(),
        "gene_id": last_run.get("selected_gene_id"),
        "signals": last_run.get("signals", []),
        "mutation": mutation,
        "blast_radius": blast_radius,
        "diff_snapshot": diff_snapshot,
        # S26 honest score: a MEASURED cascade result (1.0 = all stages green);
        # an unvalidated success claims nothing (score=None + marker) so the
        # ledger distinguishes "tested good" from "never tested".
        "outcome": (
            {"status": "success", "score": outcome_score}
            if validation_result
            else {"status": "success", "score": None, "unvalidated": True}
        ),
        "execution_trace": trace,
        **_lineage_fields(),
    }
    if fitness_verdict is not None:
        event["fitness_gate"] = fitness_verdict
    if anchor_result is not None:
        # Compact record (per-case verdict + failure tails only) — the audit
        # trail that a verifier-surface mutation passed the frozen contracts.
        cases: list[dict[str, Any]] = []
        for c in anchor_result.get("results", []):
            row: dict[str, Any] = {"id": c.get("id"), "ok": c.get("ok")}
            if not c.get("ok"):
                row["stderr_tail"] = str(c.get("stderr"))[-300:]
            cases.append(row)
        event["anchor_result"] = {
            "ok": anchor_result.get("ok"),
            "epoch": anchor_result.get("epoch"),
            "skipped": anchor_result.get("skipped"),
            "cases": cases,
        }
    if validation_result is not None:
        # RSI P0-2 (round-16): per-stage durations feed the meta-report
        # efficiency panel (time per validated gain, not just rounds).
        event["validation_timing"] = _timing_block(validation_result)
    if validation_report is not None:
        event["validation_report"] = validation_report
    if gate_result is not None:
        payload = gate_result.model_dump()
        if ACCEPTANCE_SHADOW and not gate_result.accepted:
            payload["shadow"] = True
            payload["would_accept"] = False
        event["acceptance_result"] = payload
    if bench_pack_verdict is not None:
        # Compact record: which frozen pack ruled, its digest, and the
        # per-task val scores the acceptance rested on (external fitness).
        event["bench_pack"] = {
            key: bench_pack_verdict.get(key)
            for key in (
                "pack",
                "digest",
                "split",
                "score",
                "baseline",
                "verdict",
                "soft_accept",
                "per_task",
            )
        }
    if eval_meta.get("reason") not in ("flag_off", "skipped"):
        event["eval_workspace"] = eval_meta
    if proposal_report is not None:
        event["proposal"] = proposal_report
    append_event_jsonl(event)

    # S27 wiki layer: evidence never rolls back. Improved/baseline → decision
    # log; shadow-rejected (no_improvement) → skill-impact record so future
    # mutations do not repeat it.
    with contextlib.suppress(Exception):
        _wiki_record_outcome(event, fitness_verdict, last_run)

    # S28.1 immutable evidence: full scene snapshot, written once (a second
    # write of the same run raises — evidence is immutable by architecture).
    with contextlib.suppress(Exception):
        from evolver.gep.evidence import save_evidence

        save_evidence(
            str(event.get("run_id") or event["id"]),
            event["id"],
            {
                "event": event,
                "validation_result": validation_result,
                "fitness_verdict": fitness_verdict,
                "gate": gate_result.model_dump() if gate_result else None,
            },
        )

    # Generate narrative and reflection
    with contextlib.suppress(Exception):
        record_narrative_and_reflection(event)

    with contextlib.suppress(Exception):
        post_solidify_hooks(event, last_run)

    # Sprint 23 soak fix + Soft-default UX (2026-10-31): NO auto git commit.
    # The worktree changes remain as the host left them (staged/unstaged unchanged).
    # Optional later human path: `evolver session accept` for publish.
    # Commenting out automatic commit for soft-default permanent policy.
    # if cascade_mode:
    #     landed_ids = last_run.get("landed_gene_ids") or []
    #     label = (
    #         (landed_ids[0] if isinstance(landed_ids, list) and landed_ids else None)
    #         or last_run.get("selected_gene_id")
    #         or "mutation"
    #     )
    #     _commit_mutation(cwd, f"{label} {event['id']}")

    # Update solidify state
    state["last_solidify"] = {
        "run_id": last_run.get("run_id"),
        "timestamp": event["timestamp"],
        "outcome": "success",
    }
    state_path = get_solidify_state_path()
    tmp = state_path.with_name(f"{state_path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp.replace(state_path)

    result: dict[str, Any] = {
        "ok": True,
        "outcome": "promoted",
        "event_id": event["id"],
        "blast_radius": blast_radius,
        # Charter: the host's primary_score sources from the cascade-or-gate
        # result — expose the measured cascade score on the return surface,
        # not only inside the persisted event (round-79).
        "score": outcome_score,
    }

    # Soft-default UX: no-git warnings stay soft-continue (infra condition,
    # not a Candidate verdict).
    all_warnings = list(no_git_warnings)
    if no_git_repo:
        result["severity"] = "soft"
        if all_warnings:
            result["warnings"] = all_warnings
        result["no_git_repo"] = True
        result["next_steps"] = [
            "Review warnings above",
            "Soft-continue under permanent soft-default policy",
            "Experience has been written to state_root for this cycle",
        ]

    # Soft-default UX (Task 5): add experience_written for MCP visibility
    # Track what was written to state_root this cycle
    experience_written: dict[str, list[str]] = {
        "genes": [],
        "episodes": [],
        "events": [event["id"]],  # Always write an event
    }

    # Gene was selected and event created, record it
    if last_run.get("selected_gene_id"):
        experience_written["genes"].append(str(last_run["selected_gene_id"]))

    # If episode was recorded (from episode_record in swarm layer)
    # it will be added by the caller; we provide the structure
    result["experience_written"] = experience_written

    if bench_pack_verdict is not None:
        result["bench_pack"] = {
            "score": bench_pack_verdict.get("score"),
            "baseline": bench_pack_verdict.get("baseline"),
            "verdict": bench_pack_verdict.get("verdict"),
            "reason": bench_pack_verdict.get("reason"),
            "accept": bench_pack_verdict.get("accept"),
            "soft_accept": bench_pack_verdict.get("soft_accept"),
            "soft_reason": bench_pack_verdict.get("soft_reason"),
            "warnings": bench_pack_verdict.get("warnings"),
            "next_steps": bench_pack_verdict.get("next_steps"),
            "commands": bench_pack_verdict.get("commands"),
        }
        if bench_pack_verdict.get("soft_accept"):
            result["soft_accept"] = True
            # Merge pack soft-accept warnings with validation/no-git warnings
            # instead of overwriting (soft-default UX needs both visible).
            merged = list(result.get("warnings") or [])
            for w in bench_pack_verdict.get("warnings") or []:
                if w not in merged:
                    merged.append(w)
            if merged:
                result["warnings"] = merged
            if bench_pack_verdict.get("next_steps"):
                result["next_steps"] = list(bench_pack_verdict["next_steps"])
            if bench_pack_verdict.get("commands"):
                result["commands"] = list(bench_pack_verdict["commands"])
            if bench_pack_verdict.get("hint"):
                result["hint"] = bench_pack_verdict["hint"]
    if proposal_report is not None:
        result["proposal"] = proposal_report
    if resolved_tier:
        result["validation_tier"] = resolved_tier
    if validation_result is not None:
        if validation_result.get("duration_ms") is not None:
            result["validation_duration_ms"] = validation_result["duration_ms"]
        if event.get("validation_timing") is not None:
            result["validation_timing"] = event["validation_timing"]
    if resolved_tier == "L0" and changed_for_plan:
        with contextlib.suppress(Exception):
            from evolver.gep.import_graph import spawn_l1_guardian_background

            target_gid = landed_head or gene_id
            spawn_l1_guardian_background(
                cwd,
                changed_for_plan,
                gene_id=target_gid,
                run_id=run_id_str,
            )
    return result


__all__ = [
    "adapt_gene_from_learning",
    "build_soft_failure_learning_signals",
    "classify_failure_mode",
    "record_landed_gene_ids",
    "solidify",
    "write_state_for_solidify",
]
