"""Pre-compaction checkpoint gate (VISTA compact hook analogue).

When the marker file exists, mutation tools refuse and tell the host to
write ``WORKING_SESSION.md`` first. The marker is set by a ``precompact``
hook or by four consecutive failed solidify results. Clearing it is the
checkpoint tool's job. The marker lives under ``<EVOLUTION_DIR>/``.

The Claude PreCompact hook asks :func:`precompact_decision` whether native
compaction may proceed: it blocks until the checkpoint is written, at most
once per request, so a full context is never stalled.

No Node.js equivalent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from evolver.gep.paths import get_evolution_dir

MARKER_FILENAME: Final = "compact_checkpoint.requested"
READY_FILENAME: Final = "compact_checkpoint.ready"
STREAK_FILENAME: Final = "compact_reject_streak.json"
REJECT_STREAK_BEFORE_CHECKPOINT: Final = 4

_HOOK_REASON: Final = "precompact_hook"
_STEER: Final = (
    "Context compaction is pending. Call `swarm_checkpoint_working` with your "
    "current hypothesis state, ruled-out approaches, and key episode IDs "
    "before using any other tool."
)


def marker_path() -> Path:
    return get_evolution_dir() / MARKER_FILENAME


def ready_path() -> Path:
    return get_evolution_dir() / READY_FILENAME


def streak_path() -> Path:
    return get_evolution_dir() / STREAK_FILENAME


def checkpoint_pending() -> bool:
    return marker_path().is_file()


def request_checkpoint(reason: str) -> Path:
    """Create the marker if it is absent. An existing marker is left as-is."""
    path = marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(f"{reason.strip() or 'requested'}\n", encoding="utf-8")
    return path


def clear_checkpoint() -> bool:
    """Remove the marker. Returns whether a marker was present.

    A marker the PreCompact hook blocked on leaves a ready file behind, so
    the compaction it held back may proceed.
    """
    path = marker_path()
    if not path.is_file():
        return False
    blocked = path.read_text(encoding="utf-8").strip() == _HOOK_REASON
    path.unlink()
    if blocked:
        ready_path().write_text(f"{_HOOK_REASON}\n", encoding="utf-8")
    return True


def precompact_decision() -> dict[str, str]:
    """The Claude PreCompact hook's answer; ``{}`` lets compaction proceed.

    A checkpoint written since the last block releases one compaction. A
    request already blocked once is let through, marker kept, so the tools
    stay gated. Otherwise the marker is set and compaction is blocked.
    """
    ready = ready_path()
    if ready.is_file():
        ready.unlink()
        return {}
    marker = marker_path()
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == _HOOK_REASON:
        return {}
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{_HOOK_REASON}\n", encoding="utf-8")
    return {"decision": "block", "reason": _STEER}


def pending_block() -> dict[str, Any] | None:
    """The refusal payload mutation tools return while the marker is set."""
    if not checkpoint_pending():
        return None
    return {
        "ok": False,
        "status": "checkpoint_required",
        "error": "checkpoint_required",
        "next_action": "call_swarm_checkpoint_working",
        "steer_message": _STEER,
    }


def note_outcome(ok: bool) -> int:
    """Count consecutive failed solidify results. The fourth requests a checkpoint.

    A success resets the streak. The counter is runtime state, not a gate input.
    """
    path = streak_path()
    streak = 0
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                raw = payload.get("streak")
                if isinstance(raw, int) and raw >= 0:
                    streak = raw
        except (OSError, json.JSONDecodeError, TypeError):
            streak = 0
    streak = 0 if ok else streak + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"streak": streak}) + "\n", encoding="utf-8")
    if streak >= REJECT_STREAK_BEFORE_CHECKPOINT:
        request_checkpoint("reject_streak")
    return streak


__all__ = [
    "MARKER_FILENAME",
    "READY_FILENAME",
    "REJECT_STREAK_BEFORE_CHECKPOINT",
    "STREAK_FILENAME",
    "checkpoint_pending",
    "clear_checkpoint",
    "marker_path",
    "note_outcome",
    "pending_block",
    "precompact_decision",
    "ready_path",
    "request_checkpoint",
    "streak_path",
]
