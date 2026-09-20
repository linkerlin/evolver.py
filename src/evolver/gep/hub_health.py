"""Shared Hub endpoint health — sticky 404 state (round-45/46).

The Hub endpoint answers 404 with wild latency variance (3.3s..15.7s observed
per call — over half the MCP tick budget). 404 is an endpoint FACT, not a
transient: this module owns the sticky state so EVERY consumer of the Hub
(the pipeline hub phase's task fetch since round-45, and the ATP hub_client
family since round-46) short-circuits behind one source of truth instead of
each burning its own dead-endpoint HTTP.

Module constants, not env knobs (soak charter). State persistence is
best-effort; a corrupt file fails open to "endpoint looks alive".
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Final

#: Consecutive 404s before the endpoint is treated as missing.
HUB_404_STICKY_THRESHOLD: Final = 3
#: Re-probe cadence once sticky — the endpoint may return or config change.
HUB_404_REPROBE_S: Final = 24 * 3600.0

_STATE_DEFAULT: Final[dict[str, Any]] = {
    "consecutive_404": 0,
    "last_probe_ts": 0.0,
    "skipped_cycles": 0,
}


def state_path() -> Path:
    from evolver.gep.paths import get_evolution_dir

    return get_evolution_dir() / "hub_endpoint_state.json"


def load_state() -> dict[str, Any]:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(_STATE_DEFAULT)
    return data if isinstance(data, dict) else dict(_STATE_DEFAULT)


def save_state(state: dict[str, Any]) -> None:
    try:
        path = state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass  # state persistence is best-effort; fetch behavior stays correct


def note_404(state: dict[str, Any]) -> dict[str, Any]:
    state["consecutive_404"] = int(state.get("consecutive_404", 0)) + 1
    state["last_probe_ts"] = time.time()
    return state


def reset_404(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("consecutive_404"):
        state["consecutive_404"] = 0
    return state


def endpoint_sticky(*, now: float | None = None) -> bool:
    """True while the endpoint is presumed missing and the TTL hasn't expired.

    Fail-open by construction: corrupt/missing state reads as threshold 0.
    """
    state = load_state()
    current = now if now is not None else time.time()
    return (
        int(state.get("consecutive_404", 0)) >= HUB_404_STICKY_THRESHOLD
        and current - float(state.get("last_probe_ts", 0.0)) < HUB_404_REPROBE_S
    )


__all__ = [
    "HUB_404_REPROBE_S",
    "HUB_404_STICKY_THRESHOLD",
    "endpoint_sticky",
    "load_state",
    "note_404",
    "reset_404",
    "save_state",
    "state_path",
]
