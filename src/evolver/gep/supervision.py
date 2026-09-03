"""HOTL supervision — human-on-the-loop overlay for the swarm (v1.101.0).

Autonomy spectrum counterpart to the HITL gate (evolver.gep.hitl): HITL
blocks on a per-decision basis (human *in* the loop); HOTL keeps the loop
autonomous while a supervisor rides on top of it — pause/resume, veto
patterns, and steering directives. Neither blocks healthy operation by
default: the supervisor acts through intervention, and silence means "keep
evolving" (except for the tripwire below).

Surfaces:

- state machine ``running``/``paused`` — ``swarm_tick`` refuses to run a new
  cycle while paused (graceful drain; a cycle in flight completes);
- tripwire — ``EVOLVER_SUPERVISION_AUTO_PAUSE_STREAK`` consecutive degraded
  feedback reports flip the state to ``paused`` (fuse for an absent human);
- vetoes — substring patterns (gene id, run id, subject); checked at tick
  post-selection (prompt withheld) and again at the solidify gate;
- directives — human steering text injected as ``supervision:directive:``
  pending signals (same channel as feedback gradients) so the next cycle's
  selection and dispatch prompt see it.

Every mutation is journaled (``supervision_events.jsonl``). The HITL gate
stays orthogonal: HOTL decides *whether* the loop runs, HITL decides
*whether a specific high-risk action* may proceed.
"""

from __future__ import annotations

import datetime
import json
import secrets
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

SUPERVISION_STATES: Final = ("running", "paused")
DIRECTIVE_SIGNAL_PREFIX: Final = "supervision:directive:"
_DIRECTIVE_SIGNAL_MAX_CHARS: Final = 120
_DIRECTIVE_KEEP: Final = 20
_VETO_KEEP: Final = 50


class Directive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    by: str = "human"
    at: str


class Veto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    pattern: str
    by: str = "human"
    at: str
    note: str = ""


class SupervisionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["SwarmSupervision"] = "SwarmSupervision"
    state: Literal["running", "paused"] = "running"
    paused_by: str | None = None
    paused_at: str | None = None
    pause_reason: str = ""
    directives: list[Directive] = Field(default_factory=list)
    vetoes: list[Veto] = Field(default_factory=list)
    updated_at: str = ""


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def supervision_state_path() -> Path:
    from evolver.gep.paths import get_evolution_dir

    return get_evolution_dir() / "swarm_supervision.json"


def supervision_journal_path() -> Path:
    from evolver.gep.paths import get_evolution_dir

    return get_evolution_dir() / "supervision_events.jsonl"


def _journal(event: str, **fields: Any) -> None:
    path = supervision_journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"event": event, "at": _now_iso(), **fields}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_supervision() -> SupervisionState:
    path = supervision_state_path()
    if not path.exists():
        return SupervisionState(updated_at=_now_iso())
    try:
        return SupervisionState.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return SupervisionState(updated_at=_now_iso())


def _save(state: SupervisionState) -> None:
    from evolver.gep.asset_store import atomic_write_json

    state.updated_at = _now_iso()
    atomic_write_json(supervision_state_path(), state.model_dump())


def is_paused() -> bool:
    return get_supervision().state == "paused"


def set_state(paused: bool, *, by: str, reason: str = "") -> dict[str, Any]:
    state = get_supervision()
    target: Literal["running", "paused"] = "paused" if paused else "running"
    if state.state == target:
        return {"ok": True, "state": target, "changed": False}
    state.state = target
    if paused:
        state.paused_by = by
        state.paused_at = _now_iso()
        state.pause_reason = reason
    else:
        state.paused_by = None
        state.paused_at = None
        state.pause_reason = ""
    _save(state)
    _journal("paused" if paused else "resumed", by=by, reason=reason)
    return {"ok": True, "state": target, "changed": True, "by": by, "reason": reason}


def add_directive(text: str, *, by: str = "human") -> dict[str, Any]:
    """Steering order: journal it and inject a pending signal for next cycle."""
    from evolver.gep.asset_store import append_pending_signals

    text = text.strip()
    if not text:
        return {"ok": False, "error": "empty_directive"}
    directive = Directive(id=f"dir_{secrets.token_hex(5)}", text=text, by=by, at=_now_iso())
    state = get_supervision()
    state.directives.append(directive)
    state.directives = state.directives[-_DIRECTIVE_KEEP:]
    _save(state)
    signal = f"{DIRECTIVE_SIGNAL_PREFIX} {text[:_DIRECTIVE_SIGNAL_MAX_CHARS]}"
    append_pending_signals([signal])
    _journal("directive", by=by, directive_id=directive.id, text=text[:_DIRECTIVE_SIGNAL_MAX_CHARS])
    return {"ok": True, "directive_id": directive.id, "injected_signal": signal}


def add_veto(pattern: str, *, by: str = "human", note: str = "") -> dict[str, Any]:
    pattern = pattern.strip()
    if not pattern:
        return {"ok": False, "error": "empty_pattern"}
    veto = Veto(id=f"veto_{secrets.token_hex(5)}", pattern=pattern, by=by, at=_now_iso(), note=note)
    state = get_supervision()
    state.vetoes.append(veto)
    state.vetoes = state.vetoes[-_VETO_KEEP:]
    _save(state)
    _journal("veto_added", by=by, veto_id=veto.id, pattern=pattern)
    return {"ok": True, "veto_id": veto.id, "pattern": pattern}


def remove_veto(veto_id: str) -> dict[str, Any]:
    state = get_supervision()
    remaining = [v for v in state.vetoes if v.id != veto_id]
    if len(remaining) == len(state.vetoes):
        return {"ok": False, "error": "veto_not_found", "veto_id": veto_id}
    state.vetoes = remaining
    _save(state)
    _journal("veto_removed", veto_id=veto_id)
    return {"ok": True, "removed": veto_id}


def check_veto(*candidates: str) -> dict[str, Any] | None:
    """First veto whose pattern (casefolded substring) hits any candidate."""
    state = get_supervision()
    hay = [c.casefold() for c in candidates if c]
    for veto in state.vetoes:
        needle = veto.pattern.casefold()
        if any(needle in h for h in hay):
            return veto.model_dump()
    return None


def auto_pause_check() -> dict[str, Any]:
    """Tripwire: flip to paused after N consecutive degraded feedback reports."""
    from evolver.config import SUPERVISION_AUTO_PAUSE_STREAK
    from evolver.gep.feedback import EvaluationFeedback, load_recent_feedback

    streak_needed = SUPERVISION_AUTO_PAUSE_STREAK
    if streak_needed <= 0:
        return {"checked": False, "streak": 0}
    rows = load_recent_feedback(50)
    streak = 0
    for row in reversed(rows):  # newest first
        try:
            fb = EvaluationFeedback.model_validate(row)
        except Exception:
            break
        if fb.is_degraded():
            streak += 1
        else:
            break
    if streak >= streak_needed and not is_paused():
        return {
            "checked": True,
            "streak": streak,
            **set_state(
                True,
                by="auto:degraded_streak",
                reason=f"{streak} consecutive degraded feedback reports",
            ),
        }
    return {"checked": True, "streak": streak}


def supervision_summary() -> dict[str, Any]:
    state = get_supervision()
    return {
        "state": state.state,
        "paused_by": state.paused_by,
        "paused_at": state.paused_at,
        "pause_reason": state.pause_reason,
        "directives": [d.model_dump() for d in state.directives],
        "vetoes": [v.model_dump() for v in state.vetoes],
    }


__all__ = [
    "DIRECTIVE_SIGNAL_PREFIX",
    "SUPERVISION_STATES",
    "SupervisionState",
    "add_directive",
    "add_veto",
    "auto_pause_check",
    "check_veto",
    "get_supervision",
    "is_paused",
    "remove_veto",
    "set_state",
    "supervision_journal_path",
    "supervision_state_path",
    "supervision_summary",
]
