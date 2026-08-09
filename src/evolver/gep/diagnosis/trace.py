"""Trace normalization + stage segmentation for causal diagnosis.

Methodology inspired by Self-Harness (arXiv:2606.09498, ``trace.py``). No
Node.js equivalent; evolver.py self-research addition (Sprint B1).

A failed ``EvolutionEvent`` carries an ``execution_trace`` (list of validation
steps). This module normalizes those steps into :class:`NormalizedStep` and
segments them into behavioural :class:`StageRecord` objects. Per Self-Harness,
a "change" step (write/edit/patch/create) ends a stage. evolver.py traces are
coarser than Self-Harness agent message streams, so segmentation may yield a
single stage when no change step is present — the analyzer (``causal.py``)
still attributes that stage. See plan §4 Sprint B1 risk note.
"""

from __future__ import annotations

from typing import Any

from evolver.gep.diagnosis.schemas import (
    NormalizedStep,
    StageRecord,
    TerminalFailureKind,
)

#: Verbs whose presence as a command-token prefix marks a state-modifying step.
#: (Self-Harness matches tool names; evolver.py traces carry command previews,
#: so we tokenize the command and check each token's leading verb. Note ``\b``
#: is deliberately avoided: it treats ``_`` as a word char and would miss
#: ``apply_patch`` / ``write_file``.)
_CHANGE_VERBS: tuple[str, ...] = (
    "write",
    "edit",
    "patch",
    "create",
    "apply",
    "append",
    "tee",
    "mkdir",
    "touch",
    "mv",
    "cp",
    "sed",
)

#: Error-substring → terminal_failure_kind classification (deterministic).
_FAILURE_KIND_PATTERNS: list[tuple[str, TerminalFailureKind]] = [
    ("timeout", "agent_timeout"),
    ("timed out", "agent_timeout"),
    ("no module", "missing_dependency"),
    ("modulenotfound", "missing_dependency"),
    ("importerror", "missing_dependency"),
    ("filenotfounderror", "missing_required_artifact"),
    ("no such file", "missing_required_artifact"),
    ("assertion", "verifier_assertion"),
    ("assert ", "verifier_assertion"),
    ("runtimeerror", "verifier_runtime_error"),
]


def _token_verb(token: str) -> str:
    """Reduce a command token to its leading verb (strip path/extension)."""
    base = token.replace("\\", "/").split("/")[-1]
    if "." in base:
        base = base.rsplit(".", 1)[0]
    return base.lower()


def _is_change_step(entry: dict[str, Any]) -> bool:
    """True iff *entry* looks like a state-modifying step."""
    cmd = str(entry.get("command_preview") or entry.get("command") or "")
    for tok in cmd.split():
        if any(_token_verb(tok).startswith(v) for v in _CHANGE_VERBS):
            return True
    files_touched = entry.get("files_touched")
    return isinstance(files_touched, int) and files_touched > 0


def normalize_trace_steps(event: dict[str, Any]) -> list[NormalizedStep]:
    """Convert an ``EvolutionEvent`` execution trace into NormalizedSteps.

    Empty/missing traces yield an empty list. Non-dict entries are skipped and
    surviving steps are **re-indexed** contiguously (so indices stay dense for
    stage segmentation). ``summary`` prefers the ``error_signature`` (most
    diagnostic) and falls back to the command preview.
    """
    raw_trace = event.get("execution_trace")
    if not isinstance(raw_trace, list):
        return []
    steps: list[NormalizedStep] = []
    next_index = 0
    for entry in raw_trace:
        if not isinstance(entry, dict):
            continue
        summary = str(
            entry.get("error_signature") or entry.get("command_preview") or ""
        )[:200]
        steps.append(
            NormalizedStep(
                index=next_index,
                tool=str(entry.get("tool") or ""),
                is_change=_is_change_step(entry),
                summary=summary,
            )
        )
        next_index += 1
    return steps


def build_stage_records(
    steps: list[NormalizedStep],
) -> list[StageRecord]:
    """Segment *steps* into stages; a "change" step ends its stage.

    Returns ``[]`` if *steps* is empty. The final partial stage is always
    closed. Attribution fields are left at defaults ("unknown"/empty) for the
    analyzer (``causal.py``) to fill.
    """
    if not steps:
        return []
    stages: list[StageRecord] = []
    current: list[NormalizedStep] = []
    stage_index = 0
    for step in steps:
        current.append(step)
        if step.is_change:
            stages.append(
                StageRecord(
                    stage_index=stage_index,
                    steps=list(current),
                    summary=" | ".join(s.summary for s in current if s.summary),
                )
            )
            current = []
            stage_index += 1
    if current:
        stages.append(
            StageRecord(
                stage_index=stage_index,
                steps=list(current),
                summary=" | ".join(s.summary for s in current if s.summary),
            )
        )
    return stages


def classify_terminal_failure(event: dict[str, Any]) -> TerminalFailureKind:
    """Best-effort deterministic classification of an event's terminal failure.

    Inspects outcome, signals, and execution-trace error signatures. Returns
    the first matching pattern, else ``"reward_zero"`` when the outcome score
    is explicitly 0 with no other signal, else ``"unknown"``.
    """
    outcome = event.get("outcome")
    # Gather a haystack from signals + trace error signatures.
    hay_parts: list[str] = []
    for sig in event.get("signals") or []:
        hay_parts.append(str(sig))
    for entry in event.get("execution_trace") or []:
        if isinstance(entry, dict):
            hay_parts.append(str(entry.get("error_signature") or ""))
            hay_parts.append(str(entry.get("output_preview") or ""))
    hay = " ".join(hay_parts).lower()
    for needle, kind in _FAILURE_KIND_PATTERNS:
        if needle in hay:
            return kind
    # Reward-zero fallback: failed with score 0 and no sharper signal.
    if (
        isinstance(outcome, dict)
        and str(outcome.get("status") or "").lower() == "failed"
        and outcome.get("score") == 0
    ):
        return "reward_zero"
    return "unknown"


__all__ = [
    "build_stage_records",
    "classify_terminal_failure",
    "normalize_trace_steps",
]
