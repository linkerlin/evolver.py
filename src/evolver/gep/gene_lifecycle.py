"""Gene lifecycle governance — Library Drift mitigation (RSI P1-5).

arXiv:2609.11873 §6 challenge 3: skill/gene libraries drift as they only grow;
retrieval degrades as stale entries keep winning lexical matches. The paper
asks for a full lifecycle — admission → activation → faithful use → review →
retirement — with applicability/dependency metadata, and for the two states
"retrieved" and "followed" to be measured separately.

This module implements the review/retirement rungs on top of the existing
evidence trail (``events.jsonl`` lineage: ``mutation.landed_gene_ids`` plus
the next K events, the same descendant semantics as ``ops/meta_report``):

- ``active``       : normal selection.
- ``under_review`` : zero-work evidence (N evaluable landings, zero resolved)
                     — score-penalized but still selectable, because the
                     review window *is* the re-validation trial.
- ``retired``      : re-tried during review and still zero-work — excluded
                     from selection. Retirement never deletes the gene; only
                     a human (CLI ``gene-lifecycle reinstate``) revives it.

Honesty notes:
- Transitions are derived from the *full* event history every evaluation, so
  running twice is a no-op (idempotent) — no drifting counters.
- A corrupt state file is fail-open for selection (no false bans) but refuses
  evaluation writes entirely: clobbering bookkeeping is worse than skipping.
- No new ``EVOLVER_*`` env knobs (charter discipline); thresholds are module
  constants.

No Node.js equivalent; evolver.py self-research addition (RSI P1-5).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

# --- Thresholds (module constants, no env surface) ---

#: Evaluable landings (with observed descendants) required before judging.
LIFECYCLE_MIN_OBSERVATIONS: int = 3
#: Score multiplier while under review (penalized, not banned).
LIFECYCLE_REVIEW_PENALTY: float = 0.5
#: Descendant window — kept in lockstep with ``ops.meta_report``.
LIFECYCLE_DESCENDANT_WINDOW: int = 5

LifecycleStatus = Literal["active", "under_review", "retired"]


class GeneLifecycleStoreError(RuntimeError):
    """The lifecycle state file exists but cannot be trusted."""


class GeneLifecycleRecord(BaseModel):
    """Persisted lifecycle status for one gene id."""

    model_config = ConfigDict(extra="forbid")

    gene_id: str
    status: LifecycleStatus = "active"
    since: str = ""
    reason: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    reinstated_count: int = 0


class GeneLifecycleTransition(BaseModel):
    """One evaluator verdict (pure data; no I/O)."""

    model_config = ConfigDict(extra="forbid")

    gene_id: str
    from_status: LifecycleStatus
    to_status: LifecycleStatus
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)


# --- Pure evaluation helpers ---


def _landed_genes(event: dict[str, Any]) -> list[str]:
    mut = event.get("mutation") or {}
    ids = mut.get("landed_gene_ids") or (
        [] if not mut.get("landed_gene_id") else [mut["landed_gene_id"]]
    )
    return [str(g) for g in ids if g]


def _trigger_signals(event: dict[str, Any]) -> set[str]:
    raw = event.get("signals") or (event.get("mutation") or {}).get("trigger_signals") or []
    return {str(s) for s in raw}


def landing_stats(
    events: list[dict[str, Any]],
    *,
    window: int = LIFECYCLE_DESCENDANT_WINDOW,
) -> dict[str, dict[str, int]]:
    """Per landed gene: landings, evaluable observations, resolutions.

    A landing is a *successful* event carrying ``landed_gene_ids``. Its
    descendants are the next ``window`` events; a landing counts as
    ``resolved`` when those descendants contain no failure sharing a trigger
    signal (the meta-report definition). Landings without descendants are
    ``unknown`` and are excluded from ``observations`` — silence is not
    evidence of work.
    """
    stats: dict[str, dict[str, int]] = {}
    for idx, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        if (event.get("outcome") or {}).get("status") != "success":
            continue
        landed = _landed_genes(event)
        if not landed:
            continue
        triggers = _trigger_signals(event)
        descendants = events[idx + 1 : idx + 1 + max(1, window)]
        observed = len(descendants) > 0
        recurred = sum(
            1
            for d in descendants
            if isinstance(d, dict)
            and triggers
            and triggers & _trigger_signals(d)
            and (d.get("outcome") or {}).get("status") == "failed"
        )
        for gene_id in landed:
            row = stats.setdefault(
                gene_id,
                {"landings": 0, "observations": 0, "resolved": 0, "recurred": 0, "last_index": -1},
            )
            row["landings"] += 1
            row["last_index"] = idx
            if observed:
                row["observations"] += 1
                row["recurred"] += recurred
                if recurred == 0:
                    row["resolved"] += 1
    return stats


def evaluate_gene_lifecycle(
    events: list[dict[str, Any]],
    states: dict[str, GeneLifecycleRecord],
) -> list[GeneLifecycleTransition]:
    """Pure transition function: full event history + current state → verdicts.

    Rules (RSI P1-5):

    - ``active`` → ``under_review`` when evaluable observations reach
      :data:`LIFECYCLE_MIN_OBSERVATIONS` with zero resolved landings.
    - ``under_review`` → ``active`` when a new resolution appears after the
      review baseline (the re-validation window proved the gene can work).
    - ``under_review`` → ``retired`` when the gene was tried again during
      review (new evaluable observations) and still produced no resolution.
    - ``retired`` is terminal for the engine; only humans reinstate.
    """
    stats = landing_stats(events)
    transitions: list[GeneLifecycleTransition] = []
    for gene_id in sorted(stats):
        row = stats[gene_id]
        observations = int(row["observations"])
        resolved = int(row["resolved"])
        record = states.get(gene_id)
        status: LifecycleStatus = record.status if record else "active"
        if status == "retired":
            continue
        if status == "active":
            if observations >= LIFECYCLE_MIN_OBSERVATIONS and resolved == 0:
                transitions.append(
                    GeneLifecycleTransition(
                        gene_id=gene_id,
                        from_status="active",
                        to_status="under_review",
                        reason="zero_work_evidence",
                        evidence={
                            "observations": observations,
                            "resolved": resolved,
                            "recurred": int(row["recurred"]),
                            "observations_at_review": observations,
                            "resolved_at_review": resolved,
                        },
                    )
                )
            continue
        # under_review
        evidence = record.evidence if record else {}
        baseline_observations = int(cast(int, evidence.get("observations_at_review", 0)))
        baseline_resolved = int(cast(int, evidence.get("resolved_at_review", 0)))
        if resolved > baseline_resolved:
            transitions.append(
                GeneLifecycleTransition(
                    gene_id=gene_id,
                    from_status="under_review",
                    to_status="active",
                    reason="revalidated",
                    evidence={
                        "observations": observations,
                        "resolved": resolved,
                        "baseline_observations": baseline_observations,
                        "baseline_resolved": baseline_resolved,
                    },
                )
            )
        elif observations > baseline_observations:
            transitions.append(
                GeneLifecycleTransition(
                    gene_id=gene_id,
                    from_status="under_review",
                    to_status="retired",
                    reason="zero_work_after_review",
                    evidence={
                        "observations": observations,
                        "resolved": resolved,
                        "baseline_observations": baseline_observations,
                        "baseline_resolved": baseline_resolved,
                    },
                )
            )
    return transitions


# --- Persistence ---


def lifecycle_path() -> Path:
    from evolver.gep.paths import get_gep_assets_dir

    return get_gep_assets_dir() / "gene_lifecycle.json"


def lifecycle_audit_path() -> Path:
    from evolver.gep.paths import get_gep_assets_dir

    return get_gep_assets_dir() / "gene_lifecycle.jsonl"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_lifecycle(*, strict: bool = False) -> dict[str, GeneLifecycleRecord]:
    """Load lifecycle records; missing file → ``{}``.

    ``strict=True`` raises :class:`GeneLifecycleStoreError` on unreadable
    files or a malformed top-level shape (evaluation must refuse to clobber
    bookkeeping it cannot understand). Individual malformed records are
    skipped either way. ``strict=False`` (the selector path) fails open:
    unreadable bookkeeping must never fabricate bans.
    """
    path = lifecycle_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if strict:
            raise GeneLifecycleStoreError(f"unreadable lifecycle store: {exc}") from exc
        logger.warning("[gene_lifecycle] unreadable store ignored (fail-open): %s", exc)
        return {}
    if not isinstance(raw, dict):
        if strict:
            raise GeneLifecycleStoreError("lifecycle store top level is not an object")
        return {}
    genes = raw.get("genes")
    if genes is None:
        return {}
    if not isinstance(genes, dict):
        if strict:
            raise GeneLifecycleStoreError("lifecycle store 'genes' is not an object")
        return {}
    out: dict[str, GeneLifecycleRecord] = {}
    for gene_id, row in genes.items():
        if not isinstance(row, dict):
            continue
        payload = {**row, "gene_id": row.get("gene_id") or str(gene_id)}
        try:
            out[str(gene_id)] = GeneLifecycleRecord.model_validate(payload)
        except ValidationError:
            logger.debug("[gene_lifecycle] skipping malformed record %s", gene_id)
    return out


def load_lifecycle_sets() -> tuple[set[str], set[str]]:
    """Selector view: ``(retired_ids, under_review_ids)``; corrupt → empty."""
    records = load_lifecycle(strict=False)
    retired = {gid for gid, rec in records.items() if rec.status == "retired"}
    under_review = {gid for gid, rec in records.items() if rec.status == "under_review"}
    return retired, under_review


def status_map(records: dict[str, GeneLifecycleRecord] | None = None) -> dict[str, str]:
    """Plain ``gene_id → status`` map for read-only telemetry consumers."""
    loaded = load_lifecycle(strict=False) if records is None else records
    return {gid: rec.status for gid, rec in loaded.items()}


def _write_state(states: dict[str, GeneLifecycleRecord], ts: str) -> None:
    from evolver.gep.asset_store import atomic_write_json

    payload = {
        "version": 1,
        "updated_at": ts,
        "genes": {gid: rec.model_dump() for gid, rec in sorted(states.items())},
    }
    atomic_write_json(lifecycle_path(), payload)


def _append_audit(record: dict[str, Any]) -> None:
    from evolver.gep.asset_store import append_jsonl

    append_jsonl(lifecycle_audit_path(), record)


def evaluate_and_apply(
    events: list[dict[str, Any]],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    """Evaluate the full history under lock and persist any transitions.

    Returns ``{"ok": True, "transitions": [...]}`` (empty when nothing
    changed) or ``{"ok": False, "error": ...}`` when the store is corrupt.
    """
    from evolver.gep.asset_store import with_file_lock

    with with_file_lock(target_path=lifecycle_path()):
        try:
            states = load_lifecycle(strict=True)
        except GeneLifecycleStoreError as exc:
            logger.warning("[gene_lifecycle] evaluation refused: %s", exc)
            return {"ok": False, "error": "lifecycle_store_corrupt", "detail": str(exc)}
        transitions = evaluate_gene_lifecycle(events, states)
        if not transitions:
            return {"ok": True, "transitions": []}
        ts = now or _now_iso()
        for transition in transitions:
            previous = states.get(transition.gene_id)
            states[transition.gene_id] = GeneLifecycleRecord(
                gene_id=transition.gene_id,
                status=transition.to_status,
                since=ts,
                reason=transition.reason,
                evidence=transition.evidence,
                reinstated_count=previous.reinstated_count if previous else 0,
            )
            _append_audit(
                {
                    "ts": ts,
                    "actor": "engine",
                    **transition.model_dump(),
                }
            )
        _write_state(states, ts)
        return {
            "ok": True,
            "transitions": [t.model_dump() for t in transitions],
        }


def reinstate_gene(gene_id: str, *, note: str = "", now: str | None = None) -> dict[str, Any]:
    """Human-only revival (CLI ``gene-lifecycle reinstate``). Never auto-run."""
    from evolver.gep.asset_store import with_file_lock

    with with_file_lock(target_path=lifecycle_path()):
        try:
            states = load_lifecycle(strict=True)
        except GeneLifecycleStoreError as exc:
            return {"ok": False, "error": "lifecycle_store_corrupt", "detail": str(exc)}
        record = states.get(gene_id)
        if record is None:
            return {"ok": False, "error": "not_tracked", "gene_id": gene_id}
        if record.status == "active":
            return {"ok": False, "error": "already_active", "gene_id": gene_id}
        ts = now or _now_iso()
        revived = GeneLifecycleRecord(
            gene_id=gene_id,
            status="active",
            since=ts,
            reason="human_reinstate",
            evidence={"note": note[:500], "previous_status": record.status},
            reinstated_count=record.reinstated_count + 1,
        )
        states[gene_id] = revived
        _append_audit(
            {
                "ts": ts,
                "actor": "human",
                "gene_id": gene_id,
                "from_status": record.status,
                "to_status": "active",
                "reason": "human_reinstate",
                "evidence": revived.evidence,
            }
        )
        _write_state(states, ts)
        return {"ok": True, "record": revived.model_dump()}


__all__ = [
    "LIFECYCLE_DESCENDANT_WINDOW",
    "LIFECYCLE_MIN_OBSERVATIONS",
    "LIFECYCLE_REVIEW_PENALTY",
    "GeneLifecycleRecord",
    "GeneLifecycleStoreError",
    "GeneLifecycleTransition",
    "evaluate_and_apply",
    "evaluate_gene_lifecycle",
    "landing_stats",
    "lifecycle_audit_path",
    "lifecycle_path",
    "load_lifecycle",
    "load_lifecycle_sets",
    "reinstate_gene",
    "status_map",
]
