"""Main solidify cycle: apply gene, run validations, persist results, publish.

Equivalent to evolver/src/gep/solidify.js (obfuscated).
"""

from __future__ import annotations

import contextlib
import difflib
import json
import re
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any

from evolver.config import (
    ACCEPTANCE_SHADOW,
    FITNESS_CASCADE_COMMANDS,
    VALIDATION_TIMEOUT_MS,
)
from evolver.gep.acceptance.solidify_hook import gate_or_none
from evolver.gep.asset_store import (
    append_event_jsonl,
    get_last_event_id,
    read_json_if_exists,
)
from evolver.gep.cognition import post_solidify_hooks, record_solidify_failure
from evolver.gep.execution_trace import build_execution_trace
from evolver.gep.feature_flags import is_enabled
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


def _run_validations(
    commands: list[Any],
    cwd: Path,
    *,
    cascade: bool = False,
) -> dict[str, Any]:
    """Run validation commands; ``cascade`` short-circuits on first failure."""
    results: list[dict[str, Any]] = []
    overall_ok = True
    started_at = time.time() * 1000.0
    for cmd in commands:
        argv, display, timeout_ms = _normalize_validation_command(cmd)
        result: dict[str, Any] = {
            "command": display,
            "ok": False,
            "stdout": "",
            "stderr": "",
        }
        timeout_s = (
            timeout_ms / 1000.0 if timeout_ms is not None else VALIDATION_TIMEOUT_MS / 1000.0
        )
        try:
            proc = subprocess.run(
                argv,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
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
        if cascade and not result["ok"]:
            break
    finished_at = time.time() * 1000.0
    return {
        "ok": overall_ok,
        "results": results,
        "started_at": started_at,
        "finished_at": finished_at,
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


def _apply_acceptance_gate(
    gate_result: Any,
    last_run: dict[str, Any],
    cwd: Path,
) -> dict[str, Any] | None:
    """Handle a rejection from the acceptance gate; None → gate passed/absent."""
    if gate_result is None or gate_result.accepted:
        return None
    # Sprint 22.5 shadow mode: record the verdict on the event but never
    # enforce (gray-scale — measure interception/false-kill rates first).
    if ACCEPTANCE_SHADOW:
        return None
    rollback_tracked(cwd=cwd, include_untracked=False)
    rollback_new_untracked_files(_disposable_untracked(cwd), cwd=cwd)
    record_solidify_failure(last_run, error="acceptance_gate_rejected")
    return {
        "ok": False,
        "error": "acceptance_gate_rejected",
        "details": {"acceptance": gate_result.model_dump()},
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


def get_fitness_cascade_commands() -> list[dict[str, Any]]:
    """Engine-owned fitness cascade (deep copy; never trusts mutation input)."""
    return [{**spec, "command": list(spec["command"])} for spec in FITNESS_CASCADE_COMMANDS]


def _lineage_fields() -> dict[str, Any]:
    """Sprint 22.6 (GEPA ancestry): link each event to its predecessor."""
    if not is_enabled("enable_lineage_lessons"):
        return {}
    parent = get_last_event_id()
    return {"parent_event_id": parent} if parent else {}


def _normalize_change_text(text: str) -> str:
    """Reduce a diff or raw file content to its changed-content tokens:
    keep ``+``/``-`` payload lines from diffs, else the raw lines; drop
    hunk headers/metadata so a diff and its bare content compare alike."""
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("@@", "diff --git", "index ", "--- ", "+++ ", "new file")):
            continue
        if line[:1] in ("+", "-"):
            lines.append(stripped[1:].strip())
        else:
            lines.append(stripped)
    return "".join(lines).casefold()


def _diff_similarity(a: str, b: str, *, cap: int = 4_000) -> float:
    """Change-text similarity for the novelty gate (Sprint 23.1).

    # ponytail: SequenceMatcher ratio on capped normalized change text —
    # swap for embeddings if near-duplicate paraphrases ever slip past.
    """
    na = _normalize_change_text(a)[:cap]
    nb = _normalize_change_text(b)[:cap]
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb, autojunk=False).ratio()


NOVELTY_SIMILARITY_THRESHOLD: float = 0.9

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
# Below this many normalized change-text chars, containment matching is too
# trigger-happy to trust (any small capsule would match any large mutation).
_CONTAINMENT_MIN_CHARS: int = 40


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
    accepted). Stages exactly the changed+disposable-untracked files."""
    try:
        from evolver.gep.git_ops import run_cmd

        targets = [
            f
            for f in dict.fromkeys(git_list_changed_files(cwd) + _disposable_untracked(cwd))
            if f
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


def _novelty_fingerprint(cwd: Path) -> str:
    """Content fingerprint for the novelty gate: tracked diff + untracked
    file contents (a fresh mutation is often entirely untracked, which
    ``git diff HEAD`` misses — found by Sprint 23 calibration). Both parts
    are filtered to disposable paths: workspaces that COMMIT engine state
    (.evolver/memory) must not have their own event log pollute the diff
    (soak round-2)."""
    from evolver.gep.git_ops import try_run_cmd

    parts: list[str] = []
    changed = [f for f in git_list_changed_files(cwd) if _is_disposable_path(f)]
    if changed:
        parts.append(try_run_cmd(["diff", "HEAD", "--", *changed], cwd=cwd))
    for rel in git_list_untracked_files(cwd):
        if not _is_disposable_path(rel):
            continue
        try:
            parts.append((cwd / rel).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(parts)


def _novelty_duplicate_diff(cwd: Path) -> bool:
    """True when the working-tree mutation near-duplicates a recent capsule
    OR a recent event's diff snapshot (soak round-1: solidify never creates
    capsules — distill does — so a capsule-only corpus left the gate blind)."""
    try:
        from evolver.gep.asset_store import load_capsules, read_all_events

        current = _novelty_fingerprint(cwd)
        if not current.strip():
            return False
        norm_current = _normalize_change_text(current)
        priors: list[str] = [str(c.get("diff") or "") for c in load_capsules()[-20:]]
        priors += [str(e.get("diff_snapshot") or "") for e in read_all_events()[-20:]]
        for prior in priors:
            if not prior:
                continue
            if _diff_similarity(current, str(prior)) >= NOVELTY_SIMILARITY_THRESHOLD:
                return True
            # Containment: an exact re-application adds engine/cache noise
            # around the change, which dilutes the ratio below threshold
            # (E2E calibration round 2). A sufficiently large normalized
            # capsule text appearing verbatim inside the fingerprint is a
            # duplicate regardless of the noise.
            # ponytail: substring containment, not alignment — swap for
            # embedding containment if paraphrased duplicates ever slip past.
            norm_prior = _normalize_change_text(str(prior))
            if len(norm_prior) >= _CONTAINMENT_MIN_CHARS and norm_prior in norm_current:
                return True
    except Exception:
        return False
    return False


def _handle_cascade_validation_failure(
    *,
    last_run: dict[str, Any],
    mutation: dict[str, Any],
    cwd: Path,
    validation_result: dict[str, Any],
    validation_report: dict[str, Any] | None,
) -> dict[str, Any]:
    """Sprint 22.2 graded failure: blast radius captured *before* rollback, a
    failed EvolutionEvent lands in events.jsonl (feeds the repair-loop breaker
    and signal-history modulation), and the memory-graph failure outcome
    carries a partial-credit score."""
    score = _cascade_score(validation_result["results"])
    failed_blast = _compute_blast_radius()
    # cwd must be explicit: without it the rollback targets the process cwd
    # (the engine's own repo), not the workspace (Sprint 23 test finding).
    # include_untracked=False + selective disposal: engine state dirs that
    # the workspace does not gitignore must survive (E2E calibration bug).
    rollback_tracked(cwd=cwd, include_untracked=False)
    rollback_new_untracked_files(_disposable_untracked(cwd), cwd=cwd)
    append_event_jsonl(
        {
            "type": "EvolutionEvent",
            "id": f"evt_{int(time.time() * 1000)}_{secrets.token_hex(4)}",
            "run_id": last_run.get("run_id") or (last_run.get("mutation") or {}).get("id"),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime())
            + f"{int((time.time() % 1) * 1000):03d}Z",
            "gene_id": last_run.get("selected_gene_id"),
            "signals": last_run.get("signals", []),
            "mutation": mutation,
            "blast_radius": failed_blast,
            "outcome": {"status": "failed", "score": score, "error": "validation_failed"},
            **_lineage_fields(),
        }
    )
    record_solidify_failure(last_run, error="validation_failed", score=score)
    details = dict(validation_result)
    details["score"] = score
    if validation_report is not None:
        details["validation_report"] = validation_report
    return {"ok": False, "error": "validation_failed", "details": details}


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
    # Sprint 22.2 (enable_fitness_cascade): the validation set is engine-owned
    # (config FITNESS_CASCADE_COMMANDS). mutation.validation comes from
    # external LLM output (distill) and is never executed in this mode.
    cascade_mode = is_enabled("enable_fitness_cascade") and not skip_validation
    if cascade_mode:
        validation_commands = get_fitness_cascade_commands()
    else:
        validation_commands = mutation.get("validation") or []

    # Sprint 23.1 (enable_novelty_gate, ShinkaEvolve rejection sampling):
    # reject near-duplicate mutations BEFORE paying for the expensive cascade.
    if cascade_mode and is_enabled("enable_novelty_gate") and _novelty_duplicate_diff(cwd):
        failed_blast = _compute_blast_radius()
        rollback_tracked(cwd=cwd, include_untracked=False)
        rollback_new_untracked_files(_disposable_untracked(cwd), cwd=cwd)
        append_event_jsonl(
            {
                "type": "EvolutionEvent",
                "id": f"evt_{int(time.time() * 1000)}_{secrets.token_hex(4)}",
                "run_id": last_run.get("run_id") or (last_run.get("mutation") or {}).get("id"),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime())
                + f"{int((time.time() % 1) * 1000):03d}Z",
                "gene_id": last_run.get("selected_gene_id"),
                "signals": last_run.get("signals", []),
                "mutation": mutation,
                "blast_radius": failed_blast,
                "outcome": {"status": "failed", "score": 0.0, "error": "novelty_duplicate"},
                **_lineage_fields(),
            }
        )
        record_solidify_failure(last_run, error="novelty_duplicate", score=0.0)
        return {
            "ok": False,
            "error": "novelty_duplicate",
            "details": {"blast_radius": failed_blast},
        }

    validation_result: dict[str, Any] | None = None
    validation_report: dict[str, Any] | None = None
    if not skip_validation and validation_commands:
        validation_result = _run_validations(validation_commands, cwd, cascade=cascade_mode)
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
                return _handle_cascade_validation_failure(
                    last_run=last_run,
                    mutation=mutation,
                    cwd=cwd,
                    validation_result=validation_result,
                    validation_report=validation_report,
                )
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
    # validation failure). Returns None when the gate is disabled or errored.
    gate_result = gate_or_none(last_run, cwd)
    if (rejected := _apply_acceptance_gate(gate_result, last_run, cwd)) is not None:
        return rejected

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
        **_lineage_fields(),
    }
    if validation_report is not None:
        event["validation_report"] = validation_report
    if gate_result is not None:
        payload = gate_result.model_dump()
        if ACCEPTANCE_SHADOW and not gate_result.accepted:
            payload["shadow"] = True
            payload["would_accept"] = False
        event["acceptance_result"] = payload
    append_event_jsonl(event)

    # Generate narrative and reflection
    with contextlib.suppress(Exception):
        record_narrative_and_reflection(event)

    with contextlib.suppress(Exception):
        post_solidify_hooks(event, last_run)

    # Sprint 23 soak fix: atomic evolution steps — commit accepted mutations
    # in cascade mode so later failure rollbacks stop at the last acceptance.
    if cascade_mode:
        _commit_mutation(cwd, f"{last_run.get('selected_gene_id') or 'mutation'} {event['id']}")

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
