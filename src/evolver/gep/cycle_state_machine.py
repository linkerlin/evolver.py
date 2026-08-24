"""Cycle state machine — explicit stage lattice + event→stage mapping.

Concept harvest from Node v2 ``cycle/stateMachine.d.ts`` + the
``cycleTimeline`` projector (behavioral re-implementation; no code copied).
Pure functions only: no I/O, no clock, no rng — safe to unit-test and to
call from projectors.

Stage lattice (forward-only)::

    none → started → signals_collected → gene_selected → mutation_built
         → solidified | failed | aborted   (terminal)

``stage_for_event`` maps this repo's event vocabulary onto the lattice;
unknown event types map to ``None`` (no stage change). Sprint 24.2
(演进方案.md §9 概念收割 #2).
"""

from __future__ import annotations

from dataclasses import dataclass, field

STAGE_NONE: str = "none"
STAGE_STARTED: str = "started"
STAGE_SIGNALS_COLLECTED: str = "signals_collected"
STAGE_GENE_SELECTED: str = "gene_selected"
STAGE_MUTATION_BUILT: str = "mutation_built"
STAGE_SOLIDIFIED: str = "solidified"
STAGE_FAILED: str = "failed"
STAGE_ABORTED: str = "aborted"

#: Stage lattice in strict forward order (index = rank).
STAGE_ORDER: tuple[str, ...] = (
    STAGE_NONE,
    STAGE_STARTED,
    STAGE_SIGNALS_COLLECTED,
    STAGE_GENE_SELECTED,
    STAGE_MUTATION_BUILT,
    STAGE_SOLIDIFIED,
    STAGE_FAILED,
    STAGE_ABORTED,
)
_STAGE_RANK: dict[str, int] = {stage: rank for rank, stage in enumerate(STAGE_ORDER)}

TERMINAL_STAGES: frozenset[str] = frozenset({STAGE_SOLIDIFIED, STAGE_FAILED, STAGE_ABORTED})

#: Event type → stage. Extensible registry; unlisted types cause no change.
EVENT_STAGE_MAP: dict[str, str] = {
    "cycle_start": STAGE_STARTED,
    "run_started": STAGE_STARTED,
    "signals_classified": STAGE_SIGNALS_COLLECTED,
    "signal_gate": STAGE_SIGNALS_COLLECTED,
    "gene_selected": STAGE_GENE_SELECTED,
    "dispatch": STAGE_MUTATION_BUILT,
    "mutation_built": STAGE_MUTATION_BUILT,
    "solidify": STAGE_MUTATION_BUILT,
}


def is_valid_transition(before: str, after: str) -> bool:
    """Forward-only check: *after* must rank strictly above *before*."""
    return _STAGE_RANK.get(after, -1) > _STAGE_RANK.get(before, -1)


def stage_for_event(event: dict[str, object]) -> str | None:
    """Map one event dict onto a lattice stage; ``None`` when unmapped.

    Terminal stages come from the event payload, not the type table:
    ``EvolutionEvent`` resolves via ``outcome.status``, ``cycle_end`` via
    its own ``status``/``outcome`` field.
    """
    etype = event.get("type")
    if not isinstance(etype, str):
        return None
    if etype == "EvolutionEvent":
        outcome = event.get("outcome")
        status = outcome.get("status") if isinstance(outcome, dict) else None
        return STAGE_SOLIDIFIED if str(status or "").lower() == "success" else STAGE_FAILED
    if etype == "cycle_end":
        raw_status = event.get("status")
        if not isinstance(raw_status, str) or not raw_status:
            outcome = event.get("outcome")
            raw_status = str(outcome.get("status") or "") if isinstance(outcome, dict) else ""
        lowered = raw_status.lower() if isinstance(raw_status, str) else ""
        ok = "success" in lowered or lowered == "ok"
        return STAGE_SOLIDIFIED if ok else STAGE_FAILED
    if etype == "cycle_abort":
        return STAGE_ABORTED
    return EVENT_STAGE_MAP.get(etype)


def advance(current: str, event: dict[str, object]) -> str:
    """Return the stage after applying *event* to *current*.

    Monotonic clamp: invalid regressions and terminal-stage events leave
    the state unchanged (an event log may contain interleaved noise; the
    projection must stay stable under replay).
    """
    target = stage_for_event(event)
    if target is None or not is_valid_transition(current, target):
        return current
    return target


def build_cycle_timeline(events: list[dict[str, object]]) -> list[dict[str, object]]:
    """Project events into per-run cycle timelines (Node v2 cycleTimeline).

    Groups events by ``run_id`` (first-seen order) and replays the state
    machine within each group. Events without a usable run id are ignored.
    """

    @dataclass
    class _Row:
        run_id: str
        stage: str = STAGE_NONE
        started_at: str | None = None
        ended_at: str | None = None
        event_count: int = 0
        stages_seen: list[str] = field(default_factory=list)
        outcome_status: object = None
        outcome_error: object = None

    timelines: list[_Row] = []
    by_run: dict[str, _Row] = {}

    for evt in events:
        run_id = evt.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            continue
        row = by_run.get(run_id)
        if row is None:
            row = _Row(run_id=run_id)
            by_run[run_id] = row
            timelines.append(row)

        row.event_count += 1
        timestamp = evt.get("timestamp")
        if isinstance(timestamp, str) and timestamp:
            if row.started_at is None:
                row.started_at = timestamp
            row.ended_at = timestamp

        after = advance(row.stage, evt)
        if after != row.stage:
            row.stage = after
            row.stages_seen.append(after)

        if evt.get("type") == "EvolutionEvent":
            outcome = evt.get("outcome")
            if isinstance(outcome, dict):
                row.outcome_status = outcome.get("status")
                row.outcome_error = outcome.get("error")

    return [
        {
            "run_id": row.run_id,
            "stage": row.stage,
            "started_at": row.started_at,
            "ended_at": row.ended_at,
            "event_count": row.event_count,
            "stages_seen": row.stages_seen,
            "outcome_status": row.outcome_status,
            "outcome_error": row.outcome_error,
        }
        for row in timelines
    ]


__all__ = [
    "EVENT_STAGE_MAP",
    "STAGE_ABORTED",
    "STAGE_FAILED",
    "STAGE_GENE_SELECTED",
    "STAGE_MUTATION_BUILT",
    "STAGE_NONE",
    "STAGE_ORDER",
    "STAGE_SIGNALS_COLLECTED",
    "STAGE_SOLIDIFIED",
    "STAGE_STARTED",
    "TERMINAL_STAGES",
    "advance",
    "build_cycle_timeline",
    "is_valid_transition",
    "stage_for_event",
]
