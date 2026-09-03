"""HITL approval gate — concept harvest from EvoX (Java) HITLManager.

EvoX contract (io.leavesfly.evox.hitl.HITLManager): approval requests
auto-pass when HITL is not activated, and **fail-safe to REJECT** on timeout
or error (default 1800s). Behavioral re-implementation of that contract; no
code copied.

In the evolver swarm loop this enforces the one safety rule that was
prompt-only before v1.100.0: a high-risk solidify (``skip_validation=True``)
must carry a human approval. Semantics:

- Idempotent by ``subject``: retrying the same subject reuses the existing
  decision — a rejection or expiry stays rejected (no approval-shopping by
  re-requesting); a fresh attempt needs a fresh subject (e.g. new run_id).
- ``EVOLVER_HITL_MODE=off`` auto-approves but still journals the decision
  (audit trail); ``on`` requires ``resolve_approval`` (CLI ``evolver hitl
  approve/reject`` or the MCP relay tool).
- A pending request past its TTL is marked ``expired`` and evaluates to
  REJECT — silence never authorizes.
"""

from __future__ import annotations

import datetime
import json
import secrets
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

APPROVAL_STATUSES: Final = ("pending", "approved", "rejected", "expired")


class ApprovalRequest(BaseModel):
    """One HITL gate decision record (journal + state)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["HITLApproval"] = "HITLApproval"
    id: str
    subject: str
    risk_reason: str
    detail: str = ""
    requested_by: str = "swarm"
    created_at: str
    ttl_ms: int
    expires_at: str
    status: Literal["pending", "approved", "rejected", "expired"] = "pending"
    decided_at: str | None = None
    decided_by: str | None = None
    note: str = ""


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _now_iso() -> str:
    return _utcnow().isoformat()


def _parse(ts: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(ts)


def hitl_state_path() -> Path:
    from evolver.gep.paths import get_evolution_dir

    return get_evolution_dir() / "hitl_approvals.json"


def hitl_journal_path() -> Path:
    from evolver.gep.paths import get_evolution_dir

    return get_evolution_dir() / "hitl_approvals.jsonl"


def _load_requests() -> list[ApprovalRequest]:
    path = hitl_state_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("requests", []) if isinstance(data, dict) else []
        return [ApprovalRequest.model_validate(r) for r in rows]
    except Exception:
        return []


def _save_requests(requests: list[ApprovalRequest]) -> None:
    from evolver.gep.asset_store import atomic_write_json

    payload = {"requests": [r.model_dump() for r in requests]}
    atomic_write_json(hitl_state_path(), payload)


def _journal(entry: dict[str, Any]) -> None:
    path = hitl_journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def hitl_mode_enabled() -> bool:
    from evolver.config import HITL_MODE

    return HITL_MODE == "on"


def _latest_for_subject(requests: list[ApprovalRequest], subject: str) -> ApprovalRequest | None:
    matches = [r for r in requests if r.subject == subject]
    return matches[-1] if matches else None


def _effective_status(req: ApprovalRequest) -> str:
    """Pending past TTL → expired (fail-safe); persisted lazily by callers."""
    if req.status == "pending" and _parse(req.expires_at) <= _utcnow():
        return "expired"
    return req.status


def request_approval(
    subject: str,
    risk_reason: str,
    detail: str = "",
    requested_by: str = "swarm",
    ttl_ms: int | None = None,
) -> dict[str, Any]:
    """Ask the gate for *subject*; idempotent per subject (see module doc)."""
    from evolver.config import HITL_TTL_MS

    requests = _load_requests()
    existing = _latest_for_subject(requests, subject)
    if existing is not None:
        if _effective_status(existing) == "expired" and existing.status == "pending":
            existing.status = "expired"
            _save_requests(requests)
            _journal({"event": "expired", "id": existing.id, "subject": subject})
        # pending → still awaiting; approved → stands; rejected/expired →
        # fail-safe stays closed until the subject changes.
        mapped = {"approved": "approved", "pending": "pending"}.get(existing.status, "rejected")
        return {
            "status": mapped,
            "request_id": existing.id,
            "subject": subject,
            "risk_reason": existing.risk_reason,
            "decided_by": existing.decided_by,
            "note": existing.note,
            "reused": True,
        }

    now = datetime.datetime.now(datetime.UTC)
    ttl = ttl_ms if ttl_ms is not None else HITL_TTL_MS
    req = ApprovalRequest(
        id=f"hitl_{secrets.token_hex(6)}",
        subject=subject,
        risk_reason=risk_reason,
        detail=detail,
        requested_by=requested_by,
        created_at=now.isoformat(),
        ttl_ms=ttl,
        expires_at=(now + datetime.timedelta(milliseconds=ttl)).isoformat(),
        status="approved" if not hitl_mode_enabled() else "pending",
        decided_at=now.isoformat() if not hitl_mode_enabled() else None,
        decided_by="auto:hitl-off" if not hitl_mode_enabled() else None,
        note="auto-approved (EVOLVER_HITL_MODE=off)" if not hitl_mode_enabled() else "",
    )
    requests.append(req)
    _save_requests(requests)
    _journal(
        {
            "event": "requested",
            "id": req.id,
            "subject": subject,
            "risk_reason": risk_reason,
            "auto_approved": not hitl_mode_enabled(),
        }
    )
    return {
        "status": req.status,
        "request_id": req.id,
        "subject": subject,
        "risk_reason": risk_reason,
        "reused": False,
    }


def resolve_approval(
    request_id: str,
    approve: bool,
    decided_by: str = "human",
    note: str = "",
) -> dict[str, Any]:
    """Record a human (or host-relayed) decision on a pending request."""
    requests = _load_requests()
    req = next((r for r in requests if r.id == request_id), None)
    if req is None:
        return {"ok": False, "error": "request_not_found", "request_id": request_id}
    if req.status != "pending":
        return {"ok": False, "error": f"not_pending:{req.status}", "request_id": request_id}
    if _effective_status(req) == "expired":
        req.status = "expired"
        _save_requests(requests)
        _journal({"event": "expired", "id": req.id, "subject": req.subject})
        return {"ok": False, "error": "expired", "request_id": request_id}

    req.status = "approved" if approve else "rejected"
    req.decided_at = _now_iso()
    req.decided_by = decided_by
    req.note = note
    _save_requests(requests)
    _journal(
        {
            "event": req.status,
            "id": req.id,
            "subject": req.subject,
            "decided_by": decided_by,
            "note": note,
        }
    )
    return {"ok": True, "status": req.status, "request_id": request_id, "subject": req.subject}


def evaluate_gate(subject: str) -> dict[str, Any]:
    """Effective gate verdict for *subject* (expired ⇒ rejected, fail-safe)."""
    requests = _load_requests()
    req = _latest_for_subject(requests, subject)
    if req is None:
        return {"status": "no_request", "subject": subject}
    effective = _effective_status(req)
    if effective == "expired" and req.status == "pending":
        req.status = "expired"
        _save_requests(requests)
        _journal({"event": "expired", "id": req.id, "subject": subject})
        effective = "expired"
    status = "rejected" if effective in ("expired", "rejected") else effective
    return {
        "status": status,
        "request_id": req.id,
        "subject": subject,
        "decided_by": req.decided_by,
        "note": req.note,
        "reason": f"source_status={effective}" if effective in ("expired", "rejected") else "",
    }


def list_pending() -> list[dict[str, Any]]:
    return [r.model_dump() for r in _load_requests() if r.status == "pending"]


def list_recent(limit: int = 20) -> list[dict[str, Any]]:
    return [r.model_dump() for r in _load_requests()[-max(1, limit) :]]


__all__ = [
    "APPROVAL_STATUSES",
    "ApprovalRequest",
    "evaluate_gate",
    "hitl_journal_path",
    "hitl_mode_enabled",
    "hitl_state_path",
    "list_pending",
    "list_recent",
    "request_approval",
    "resolve_approval",
]
