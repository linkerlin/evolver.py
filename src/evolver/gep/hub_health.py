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
#: Round-65: each failed re-probe HALVES the next wait (24h -> 12h -> 6h
#: ... floored at 1h). A persistently dead endpoint gets probed more often
#: over time (cheap single-shot probes), while a returning endpoint is
#: still caught within one window. Floor constant, not env knob.
HUB_404_REPROBE_FLOOR_S: Final = 3600.0

_STATE_DEFAULT: Final[dict[str, Any]] = {
    "consecutive_404": 0,
    "last_probe_ts": 0.0,
    "skipped_cycles": 0,
    "reprobe_count": 0,
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
    Round-65: the wait HALVES with each failed re-probe (floored at 1h) —
    a persistently dead endpoint is probed more often over time, so a
    returning endpoint is caught within one shortened window instead of
    waiting a full 24h after every failed probe.
    """
    state = load_state()
    current = now if now is not None else time.time()
    wait = max(
        HUB_404_REPROBE_S / max(1, int(state.get("reprobe_count", 0)) + 1),
        HUB_404_REPROBE_FLOOR_S if int(state.get("reprobe_count", 0)) > 0 else 0.0,
    )
    return (
        int(state.get("consecutive_404", 0)) >= HUB_404_STICKY_THRESHOLD
        and current - float(state.get("last_probe_ts", 0.0)) < wait
    )


def note_reprobe_failed(state: dict[str, Any]) -> dict[str, Any]:
    """Record that a sticky-state re-probe ran and failed (round-65)."""
    state["reprobe_count"] = int(state.get("reprobe_count", 0)) + 1
    return state


def reset_reprobe(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("reprobe_count"):
        state["reprobe_count"] = 0
    return state


def record_outcome(*, ok: bool, error_text: str = "") -> dict[str, Any]:
    """Feed the shared sticky counter from ANY Hub consumer (round-120).

    Until now only the pipeline hub phase's fetch wrote the counter — the
    ATP family (round-46) only read it. With sparse host-driven ticks days
    apart, the 3-probe threshold took three real ticks to converge and
    post_cycle's pickup burned the dead endpoint every cycle in between.
    Same honesty semantics as hub_phase: 404 counts, success resets, any
    other failure class resets (it says nothing about the endpoint's
    existence). Fresh state is loaded per observation so concurrent
    consumers never clobber each other's counts.
    """
    state = load_state()
    if ok:
        state = reset_reprobe(reset_404(state))
    elif "404" in error_text:
        state = note_404(state)
        if int(state.get("consecutive_404", 0)) >= HUB_404_STICKY_THRESHOLD:
            note_reprobe_failed(state)
    else:
        state = reset_reprobe(reset_404(state))
    save_state(state)
    return state


__all__ = [
    "HUB_404_REPROBE_FLOOR_S",
    "HUB_404_REPROBE_S",
    "HUB_404_STICKY_THRESHOLD",
    "endpoint_sticky",
    "load_state",
    "note_404",
    "note_reprobe_failed",
    "record_outcome",
    "reset_404",
    "reset_reprobe",
    "save_state",
    "state_path",
]
