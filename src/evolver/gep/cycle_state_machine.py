"""Cycle state machine — explicit stage lattice + event→stage mapping.

Concept harvest from Node v2 ``cycle/stateMachine.d.ts`` + the
``cycleTimeline`` projector (behavioral re-implementation; no code copied).
Pure functions only: no I/O, no clock, no rng — safe to unit-test and to
call from projectors.

Stage lattice (forward-only until a settlement)::

    none → started → signals_collected → gene_selected → mutation_built
         → solidified | failed | aborted   (terminal peers)

Terminal stages are peers, not a rank ladder. ``advance`` replaces one
terminal with a later terminal event (the last settlement wins) and
ignores non-terminal noise after a settlement. ``outcome_status`` is
taken from that same event, so a row cannot show ``stage=failed`` next
to ``outcome_status=success`` (a soft_failed event followed by the
success path, or a ``cycle_end`` whose ``outcome`` is the string
``"success"``).

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

#: Open-lattice rank. Terminals outrank ``mutation_built`` so a settlement
#: is a forward step, but they are peers: ``is_valid_transition`` refuses
#: to leave a terminal, and ``advance`` replaces one only for a later
#: terminal event.
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
    """Forward-only check along the open lattice.

    *after* must rank strictly above *before*. A terminal stage does not
    move this way: settlements replace each other in ``advance``.
    """
    if before in TERMINAL_STAGES:
        return False
    return _STAGE_RANK.get(after, -1) > _STAGE_RANK.get(before, -1)


def _status_is_success(text: str) -> bool:
    lowered = text.strip().lower()
    return bool(lowered) and ("success" in lowered or lowered == "ok")


def _cycle_end_status_text(event: dict[str, object]) -> str:
    """Status text for a ``cycle_end`` event.

    The pipeline field is ``status``. The WebUI observer also logs
    ``outcome`` as a plain string (``"success"`` / ``"failure"``) or as
    ``{"status": ...}``. An empty event carries no settlement.
    """
    raw_status = event.get("status")
    if isinstance(raw_status, str) and raw_status.strip():
        return raw_status.strip()
    outcome = event.get("outcome")
    if isinstance(outcome, str) and outcome.strip():
        return outcome.strip()
    if isinstance(outcome, dict):
        inner = outcome.get("status")
        if isinstance(inner, str) and inner.strip():
            return inner.strip()
        if inner is not None and not isinstance(inner, str):
            rendered = str(inner).strip()
            if rendered:
                return rendered
    return ""


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
        text = _cycle_end_status_text(event)
        if not text:
            return None
        return STAGE_SOLIDIFIED if _status_is_success(text) else STAGE_FAILED
    if etype == "cycle_abort":
        return STAGE_ABORTED
    return EVENT_STAGE_MAP.get(etype)


def outcome_matches_stage(stage: str, outcome_status: object) -> bool:
    """True when a settlement status agrees with the lattice stage.

    An empty outcome does not contradict a stage (the run may still be
    open). ``success`` / ``ok`` agree only with ``solidified``; ``aborted``
    agrees only with ``aborted``; every other status agrees only with
    ``failed``.
    """
    text = str(outcome_status or "").strip().lower()
    if not text:
        return True
    if _status_is_success(text):
        return stage == STAGE_SOLIDIFIED
    if text == "aborted":
        return stage == STAGE_ABORTED
    return stage == STAGE_FAILED


def _terminal_outcome(event: dict[str, object]) -> tuple[str, object, object] | None:
    """``(stage, outcome_status, outcome_error)`` for a settlement event."""
    stage = stage_for_event(event)
    if stage not in TERMINAL_STAGES:
        return None
    etype = event.get("type")
    if etype == "EvolutionEvent":
        outcome = event.get("outcome")
        if isinstance(outcome, dict):
            return stage, outcome.get("status"), outcome.get("error")
        return stage, None, None
    if etype == "cycle_end":
        return stage, _cycle_end_status_text(event) or None, event.get("error")
    if etype == "cycle_abort":
        reason = event.get("error")
        if reason is None:
            reason = event.get("reason")
        return stage, "aborted", reason
    return stage, None, None


def advance(current: str, event: dict[str, object]) -> str:
    """Return the stage after applying *event* to *current*.

    Non-terminals only move forward. Once a run has settled, a later
    terminal event replaces that settlement (last terminal wins) and any
    other event is noise. Replay stays deterministic.
    """
    target = stage_for_event(event)
    if target is None:
        return current
    if current in TERMINAL_STAGES:
        if target in TERMINAL_STAGES:
            return target
        return current
    if not is_valid_transition(current, target):
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

        settled = _terminal_outcome(evt)
        if settled is not None:
            _stage, status, error = settled
            row.outcome_status = status
            row.outcome_error = error

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
            "outcome_matches_stage": outcome_matches_stage(row.stage, row.outcome_status),
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
    "outcome_matches_stage",
    "stage_for_event",
]
