"""Claim nudge — gentle prompts to encourage task claiming.

Equivalent to ``evolver/src/gep/claimNudge.js`` (106 lines).

When the evolution system detects available tasks on the Hub that match
local capabilities but none have been claimed, this module generates a
non-intrusive "nudge" — a single-line suggestion injected into the session
context. Throttled to avoid nagging.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

_NUDGE_COOLDOWN_S = 3600  # 1 hour between nudges


def _nudge_state_path() -> Path:
    from evolver.gep.paths import get_evolution_dir  # noqa: PLC0415

    return get_evolution_dir() / "claim_nudge_state.json"


def _read_state() -> dict[str, Any]:
    path = _nudge_state_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _write_state(state: dict[str, Any]) -> None:
    path = _nudge_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass


def should_nudge() -> bool:
    """Return True if enough time has passed since the last nudge."""
    state = _read_state()
    last = state.get("last_nudge_ts", 0)
    return bool(time.time() - last >= _NUDGE_COOLDOWN_S)


def build_nudge(available_count: int, top_task: dict[str, Any] | None = None) -> str | None:
    """Build a nudge message if appropriate, or None to suppress.

    Parameters:
        available_count: Number of matching tasks available on the Hub.
        top_task: The highest-ROI task dict (optional).
    """
    if available_count <= 0:
        return None
    if not should_nudge():
        return None

    _write_state({"last_nudge_ts": time.time()})

    parts = [f"[Evolver] {available_count} task(s) match your capabilities on the Hub"]
    if top_task:
        task_id = top_task.get("task_id", "")
        bounty = top_task.get("bounty", top_task.get("reward", 0))
        if bounty:
            parts.append(f"(top: {task_id}, bounty={bounty})")
    parts.append("— run `evolver atp tasks` to see them.")
    return " ".join(parts)


def reset_nudge() -> None:
    """Clear nudge state (for testing or manual reset)."""
    _write_state({})


__all__ = ["build_nudge", "reset_nudge", "should_nudge"]
