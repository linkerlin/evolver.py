"""The evolution cursor — where external experience has been consumed up to.

EvoOntology keeps ``checkpoint_trajectory`` + ``checkpoint_time`` in its
state and advances them in exactly one place: ``accept()``. A Reject never
moves the cursor, because a Reject means "this was not yet understood", not
"this has been consumed". The trigger then compares incoming trajectories
against the cursor and, when enough new ones pile up, *reminds* — it never
starts a session. Opening a session stays a human act.

evolver adopts both halves:

* the cursor advances only in :func:`advance` (called from Accept);
* :func:`reminder` only reports — the caller decides, and the charter says
  the decision belongs to a human (演进方案.md §5.5).

One fix over the source: EvoOntology compares times only, so two sessions
recorded in the same second lose their ordering. evolver compares the tuple
``(recorded_at, session_id)``, which is total.

Harvested from EvoOntology ``evolution/session.py`` +
``trigger/trigger.py``; no Node.js equivalent. Charter 2026-09-26.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from evolver.gep.paths import get_evolution_dir

CURSOR_FILENAME: Final = "cursor.json"
CURSOR_FORMAT: Final = "evolver.cursor.v0"

#: OR-thresholds for the reminder (charter §5.5). Either is enough.
CURSOR_MIN_TRAJECTORIES: Final = 8
CURSOR_MAX_AGE_DAYS: Final = 7

#: Reasons.
REASON_NOT_NEWER: Final = "cursor_not_advanced"


def cursor_path() -> Path:
    """Cursor lives in the run-state dir — never in the product repo."""
    return get_evolution_dir() / CURSOR_FILENAME


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(text: Any) -> datetime | None:
    """Parse the cursor's ISO stamp. ``None`` on anything malformed — a
    damaged cursor means "no cursor", never a crash."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def load_cursor() -> dict[str, Any] | None:
    """Persisted cursor, or ``None`` when absent/unusable."""
    path = cursor_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if not isinstance(payload.get("checkpoint_time"), str):
        return None
    return payload


def save_cursor(
    *,
    recorded_at: str,
    session_id: str = "",
    trajectories: int = 0,
) -> dict[str, Any]:
    """Overwrite the cursor. Only :func:`advance` should call this."""
    path = cursor_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": CURSOR_FORMAT,
        "checkpoint_time": recorded_at,
        "checkpoint_session": session_id,
        "trajectories_at_checkpoint": int(trajectories),
        "updated_at": _now(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def is_after(cursor: dict[str, Any], recorded_at: str, session_id: str = "") -> bool:
    """Whether *(recorded_at, session_id)* sits strictly after the cursor.

    Strict, so an equal stamp does not advance it: re-Accepting the same
    moment must not silently consume the same experience twice. The tuple
    keeps same-second sessions ordered, which a pure time compare loses.
    """
    cursor_time = str(cursor.get("checkpoint_time") or "")
    cursor_session = str(cursor.get("checkpoint_session") or "")
    if not cursor_time:
        return True
    return (recorded_at, session_id) > (cursor_time, cursor_session)


def advance(
    *,
    recorded_at: str,
    session_id: str = "",
    trajectories: int = 0,
) -> dict[str, Any]:
    """Move the cursor forward — the Accept-only writer.

    Refuses anything not strictly newer than the cursor: a Reject or a
    re-run of an old session must not consume external experience.
    """
    current = load_cursor()
    if current is not None and not is_after(current, recorded_at, session_id):
        return {
            "ok": False,
            "reason": REASON_NOT_NEWER,
            "path": str(cursor_path()),
            "cursor": current,
        }
    payload = save_cursor(recorded_at=recorded_at, session_id=session_id, trajectories=trajectories)
    return {"ok": True, "reason": "cursor_advanced", "path": str(cursor_path()), "cursor": payload}


def record_trajectory(count: int = 1) -> dict[str, Any]:
    """Count an external trajectory seen since the checkpoint.

    Honest about its own limits: evolver has no external trajectory source
    wired yet, so the counter only moves when something calls this. Until
    then the reminder's trajectory arm stays at zero and only the age arm
    can fire — which is the truthful state of affairs, not a placeholder
    dressed up as a signal.
    """
    path = cursor_path()
    payload = load_cursor() or {}
    seen = int(payload.get("trajectories_seen_since") or 0) + int(count)
    payload["trajectories_seen_since"] = seen
    payload.setdefault("format", CURSOR_FORMAT)
    payload.setdefault("checkpoint_time", "")
    payload.setdefault("checkpoint_session", "")
    payload["updated_at"] = _now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "trajectories_seen_since": seen, "path": str(path)}


def reminder(
    *,
    min_trajectories: int = CURSOR_MIN_TRAJECTORIES,
    max_age_days: int = CURSOR_MAX_AGE_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Report whether enough new experience has piled up. Never acts.

    Returns a payload for the human: the trigger's whole job is to remind,
    and starting a session is a naming act the charter reserves for a human
    (§5.5). ``due`` being true is an invitation, not a command.
    """
    cursor = load_cursor()
    seen = int((cursor or {}).get("trajectories_seen_since") or 0)
    stamp = _parse((cursor or {}).get("checkpoint_time"))
    moment = now or datetime.now(UTC)

    age_days: float | None = None
    if stamp is not None:
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        age_days = round((moment - stamp).total_seconds() / 86400.0, 4)

    by_trajectory = seen >= int(min_trajectories)
    by_age = age_days is not None and age_days >= float(max_age_days)
    return {
        "due": bool(by_trajectory or by_age),
        "by_trajectory": by_trajectory,
        "by_age": by_age,
        "trajectories_seen_since": seen,
        "min_trajectories": int(min_trajectories),
        "age_days": age_days,
        "max_age_days": float(max_age_days),
        "cursor": cursor,
        "path": str(cursor_path()),
        # The reminder never opens anything; this is what the human is told.
        "action": "name a session yourself (evolver session start) — nothing starts itself",
    }


__all__ = [
    "CURSOR_FILENAME",
    "CURSOR_FORMAT",
    "CURSOR_MAX_AGE_DAYS",
    "CURSOR_MIN_TRAJECTORIES",
    "REASON_NOT_NEWER",
    "advance",
    "cursor_path",
    "is_after",
    "load_cursor",
    "record_trajectory",
    "reminder",
    "save_cursor",
]
