"""One candidate validates one primary hypothesis (演进方案.md §5.3).

Protocol source: EvoOntology ``evo-evolve/SKILL.md`` Step 2-3 — attribute the
cause to Content, Tool, or Schema, then confirm the intended mechanism has
actually changed *before* paying for a formal comparison. What moves here is
the discipline, not its three-layer ontology: this repo's dimensions are

- **content** — Gene / Capsule / living-memory strategies read while solving;
- **tool** — MCP tools, hooks, and the instrument text the host actually runs;
- **schema** — the record shape of Gene / Capsule and the selector contract.

A round without a record — or worse, one whose mechanism check cites val task
ids — never reaches the val gate. The check runs *before* the pack gate, so a
missing hypothesis cannot be laundered into a published mutation by scoring.

Environment note: the hypothesis lives with the rest of the runtime state
(``<EVOLUTION_DIR>/hypothesis.json``), outside the product repo. When the
frozen pack is unarmed there are no train ids to validate against, so the ref
check reports ``pack_armed: False`` and defers instead of pretending to pass.
"""

from __future__ import annotations

import json
import os
from typing import Any

from evolver.ops.soak_env import soak_root

#: The only three dimensions a hypothesis may claim.
DIMENSIONS: tuple[str, ...] = ("content", "tool", "schema")

#: Display labels for reports and prompts (charter wording).
DIMENSION_LABELS: dict[str, str] = {
    "content": "内容",
    "tool": "工具",
    "schema": "图式",
}

HYPOTHESIS_FILENAME: str = "hypothesis.json"
SCHEMA_VERSION: int = 1

#: Why a round was refused. Kept exhaustive so callers report, not guess.
REASON_MISSING_RECORD: str = "missing_hypothesis_record"
REASON_CORRUPT: str = "corrupt_hypothesis_record"
REASON_EMPTY_HYPOTHESIS: str = "empty_hypothesis"
REASON_BAD_DIMENSION: str = "bad_dimension"
REASON_EMPTY_FAMILY: str = "empty_mechanism_family"
REASON_EMPTY_TARGET: str = "empty_target_hook"
REASON_MISSING_CHECK: str = "missing_mechanism_check"
REASON_CHECK_NOT_OBSERVATION: str = "mechanism_check_not_observation"
REASON_VAL_REF: str = "mechanism_check_references_val"
REASON_UNKNOWN_REF: str = "mechanism_check_unknown_id"
REASON_RUN_MISMATCH: str = "hypothesis_belongs_to_another_round"

REASON_MESSAGES: dict[str, str] = {
    REASON_MISSING_RECORD: "no hypothesis was recorded for this Candidate",
    REASON_CORRUPT: "the hypothesis record is not a JSON object",
    REASON_EMPTY_HYPOTHESIS: "'hypothesis' must be a non-empty string",
    REASON_BAD_DIMENSION: (f"'dimension' must be one of {list(DIMENSIONS)} (内容 / 工具 / 图式)"),
    REASON_EMPTY_FAMILY: "'mechanism_family' must be a non-empty string",
    REASON_EMPTY_TARGET: "'target_hook' (作用点) must be a non-empty string",
    REASON_MISSING_CHECK: "'mechanism_check' must cite at least one replayable train ref",
    REASON_CHECK_NOT_OBSERVATION: (
        "'mechanism_check' must cite before/after observations on train task "
        "ids ({'id': …, 'before': what you ran, 'after': what changed}) — a "
        "bare id proves nothing was replayed"
    ),
    REASON_VAL_REF: "mechanism_check cites val task ids — the validation reserve is sealed",
    REASON_UNKNOWN_REF: "mechanism_check cites ids that are not in the frozen pack",
    REASON_RUN_MISMATCH: (
        "the recorded hypothesis belongs to another round — declare one for "
        "this Candidate (one Candidate, one hypothesis, §5.3)"
    ),
}


class HypothesisError(RuntimeError):
    """A round tried to enter the gate without a usable hypothesis."""


def hypothesis_root() -> Any:
    """Directory holding the hypothesis record (outside the product repo)."""
    from pathlib import Path

    env = os.environ.get("EVOLUTION_DIR")
    base = Path(env).expanduser() if env else soak_root() / "evolution"
    return base


def hypothesis_path() -> Any:
    from pathlib import Path

    return Path(hypothesis_root()) / HYPOTHESIS_FILENAME


def record_hypothesis(payload: dict[str, Any]) -> Any:
    """Persist this round's hypothesis. Rejects malformed records up front."""
    from pathlib import Path

    if not isinstance(payload, dict):
        raise HypothesisError(REASON_MESSAGES[REASON_CORRUPT])
    ok, reason = validate_record(payload)
    if not ok:
        raise HypothesisError(REASON_MESSAGES[reason])
    path = Path(hypothesis_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    stored = dict(payload)
    stored["schema_version"] = SCHEMA_VERSION
    stored["recorded_at"] = _now()
    path.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_hypothesis() -> dict[str, Any] | None:
    """The recorded hypothesis, or ``None`` when absent/unreadable."""
    from pathlib import Path

    path = Path(hypothesis_path())
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def clear_hypothesis() -> None:
    """Drop the record between rounds (tests and fresh runs)."""
    from pathlib import Path

    path = Path(hypothesis_path())
    if path.is_file():
        path.unlink()


def _task_ids() -> dict[str, list[str]]:
    from evolver.gep.val_seal import task_ids

    return task_ids()


def _refs(check: Any) -> tuple[str, ...]:
    """Pull task ids out of the mechanism check.

    Accepts plain string ids or dict refs (``{"id": ..., "before": ...,
    "after": ...}``) so the executor can cite observed before/after outcomes.
    """
    if not isinstance(check, list):
        return ()
    refs: list[str] = []
    for item in check:
        if isinstance(item, str) and item.strip():
            refs.append(item.strip())
        elif isinstance(item, dict):
            value = item.get("id") or item.get("task_id") or item.get("task")
            if isinstance(value, str) and value.strip():
                refs.append(value.strip())
    return tuple(refs)


def _observed(value: Any) -> bool:
    """Whether an observation field carries content.

    ``None`` and blank strings mean "not stated". Numbers count — a ``before``
    of ``0.0`` is a real measurement, and a truthiness test would drop it.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def validate_record(payload: dict[str, Any] | None) -> tuple[bool, str]:
    """Field-level validation independent of the frozen pack.

    Returns ``(ok, reason)``. Field checks always apply; ref checks need the
    pack and are reported as armed/unarmed by :func:`validate_for_gate`.
    """
    if not isinstance(payload, dict):
        return False, REASON_CORRUPT
    if not str(payload.get("hypothesis") or "").strip():
        return False, REASON_EMPTY_HYPOTHESIS
    if str(payload.get("dimension") or "") not in DIMENSIONS:
        return False, REASON_BAD_DIMENSION
    if not str(payload.get("mechanism_family") or "").strip():
        return False, REASON_EMPTY_FAMILY
    if not str(payload.get("target_hook") or "").strip():
        return False, REASON_EMPTY_TARGET
    check = payload.get("mechanism_check")
    if not isinstance(check, list) or not check:
        return False, REASON_MISSING_CHECK
    # §5.3 wants replayed evidence, not a shopping list of ids: each citation
    # must say what was run (before) and what changed (after). A bare id can
    # be copied from the pack header without ever solving anything.
    for item in check:
        if not isinstance(item, dict):
            return False, REASON_CHECK_NOT_OBSERVATION
        ref_id = item.get("id") or item.get("task_id") or item.get("task")
        if not (isinstance(ref_id, str) and ref_id.strip()):
            return False, REASON_CHECK_NOT_OBSERVATION
        if not _observed(item.get("before")) or not _observed(item.get("after")):
            return False, REASON_CHECK_NOT_OBSERVATION
    return True, ""


def validate_for_gate(
    payload: dict[str, Any] | None,
) -> tuple[bool, str, dict[str, Any]]:
    """Full gate check: fields, then ref provenance against the frozen pack.

    Returns ``(ok, reason, detail)``. ``detail`` carries ``pack_armed`` and the
    ref buckets so the failure line explains itself instead of just refusing.
    """
    ok, reason = validate_record(payload)
    if not ok:
        return (
            False,
            reason if payload is not None else REASON_MISSING_RECORD,
            {"pack_armed": bool(_task_ids()["val"])},
        )

    assert payload is not None  # narrowing for type checkers
    buckets = _task_ids()
    train = set(buckets["train"])
    val = set(buckets["val"])
    detail: dict[str, Any] = {
        "pack_armed": bool(val),
        "dimension": str(payload.get("dimension")),
        "dimension_label": DIMENSION_LABELS.get(str(payload.get("dimension")), ""),
        "refs": list(_refs(payload.get("mechanism_check"))),
    }
    if not detail["pack_armed"]:
        # Nothing to check against. Defer honestly: field discipline still
        # binds, but we do not claim the refs were proven train-only.
        detail["ref_check"] = "deferred_no_pack"
        return True, "", detail

    refs = list(detail["refs"])
    offenders = sorted(set(refs) & val)
    if offenders:
        detail["val_refs"] = offenders
        return False, REASON_VAL_REF, detail
    unknown = sorted(set(refs) - train)
    if unknown:
        detail["unknown_refs"] = unknown
        return False, REASON_UNKNOWN_REF, detail
    detail["ref_check"] = "train_only"
    return True, "", detail


def require_for_gate(
    payload: dict[str, Any] | None,
    run_id: str | None = None,
    *,
    also_accept: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    """Raise :class:`HypothesisError` unless the record may enter the gate.

    ``run_id`` is the pending round this Candidate belongs to. When the record
    carries a ``run_id`` of its own it must match — a record left over from a
    previous round must not clear this one's bar. A record without one is
    still consumed exactly once (solidify clears it after the gate), so the
    next round cannot ride on it either.

    ``also_accept`` names the round scopes that count as *this* round beside
    the swarm cycle id. There are two writers and two id systems: the host
    stamps the cycle id (``run_<ms>_<hex>``), while ``evolver session
    hypothesize`` stamps the session's own round scope (``run_1``). Both are
    "this round"; a leftover record from a previous cycle matches neither and
    is still refused.
    """
    if payload is None:
        raise HypothesisError(REASON_MESSAGES[REASON_MISSING_RECORD])
    if run_id:
        recorded = str(payload.get("run_id") or "").strip()
        accepted = {str(item).strip() for item in also_accept if str(item).strip()}
        accepted.add(str(run_id).strip())
        if recorded and recorded not in accepted:
            raise HypothesisError(
                f"{REASON_MESSAGES[REASON_RUN_MISMATCH]} "
                f"(recorded {recorded!r}, this round {str(run_id).strip()!r})"
            )
    ok, reason, detail = validate_for_gate(payload)
    if not ok:
        message = REASON_MESSAGES.get(reason, reason)
        suffix = ""
        if detail.get("val_refs"):
            suffix = f" (offending ids: {', '.join(detail['val_refs'])})"
        elif detail.get("unknown_refs"):
            suffix = f" (unknown ids: {', '.join(detail['unknown_refs'])})"
        raise HypothesisError(f"{message}{suffix}")
    return detail


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


__all__ = [
    "DIMENSIONS",
    "DIMENSION_LABELS",
    "HYPOTHESIS_FILENAME",
    "REASON_MESSAGES",
    "HypothesisError",
    "clear_hypothesis",
    "hypothesis_path",
    "hypothesis_root",
    "load_hypothesis",
    "record_hypothesis",
    "require_for_gate",
    "validate_for_gate",
    "validate_record",
]
