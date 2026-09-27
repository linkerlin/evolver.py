"""Paired evolution session - one evolution is a budget-frozen session.

Charter: 演进方案.md 2026-09-26 §5.1. The protocol comes from EvoOntology
1.1.0 ``EvolutionSession`` (``evoontology/evolution/session.py``). What moves
across is the session rule, not its five record families: the selected object
here is a library-snapshot id (content dimension) or a diff ref (schema/tool
dimension). The session machine only knows string ids.

State rules::

    running -- Reject -----------------> running (next Candidate, same session)
    running -- Accept -----------------> accepted (publish, switch active, advance)
    running -- budget spent / external -> incomplete (no publish, no advance)

A Reject, a missing hypothesis, or a finished experiment never ends a run.
Only Accept and a legitimate Incomplete are terminal. The host cannot raise
its own budget: :meth:`EvolutionSession.extend_budget` demands a named human.

Persisted outside the product repo (soak root)::

    <EVOLUTION_DIR|soak_root()/evolution>/sessions/run_N/
        run.json            status, Parent, current Candidate, frozen budget
        rounds.jsonl        one line per finished round (rejects only)
        evaluations/        stable summaries of formal Parent/Candidate scoring
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evolver.ops.soak_env import soak_root

RUNNING: str = "running"
ACCEPTED: str = "accepted"
INCOMPLETE: str = "incomplete"
TERMINAL_STATES: frozenset[str] = frozenset({ACCEPTED, INCOMPLETE})

#: Default round budget (same value as EvoOntology; only a human raises it).
DEFAULT_MAX_ROUNDS: int = 8
#: Rejects required before a judgment-based stop is allowed.
DEFAULT_MIN_REJECTS_BEFORE_INCOMPLETE: int = 2
RUN_SCHEMA_VERSION: int = 1
SESSION_SUBDIR: str = "sessions"

#: Legitimate external-stop reasons. Reject and stagnation are not among them.
INCOMPLETE_REASONS: frozenset[str] = frozenset(
    {
        "budget_exhausted",
        "user_interrupted",
        "missing_data",
        "missing_permissions",
        "unreliable_evaluation",
        "external_block",
    }
)

#: Judgment stops: these need accumulated Rejects before the run may close.
JUDGMENT_STOP_REASONS: frozenset[str] = frozenset(
    {"missing_data", "unreliable_evaluation", "external_block"}
)

#: Immediate stops: external conditions forbid continuing, Reject count ignored.
IMMEDIATE_STOP_REASONS: frozenset[str] = frozenset({"user_interrupted", "missing_permissions"})

#: The host must never confirm its own budget raise (章程 §3). ``host-agent``
#: is the actor name the swarm loop actually uses — an exact-match blacklist
#: that forgets it is a hole, so the hyphen/underscore spellings are listed
#: too and the check also refuses the ``host``/``agent``/``swarm``/``loop``/
#: ``evolver`` prefixes outright.
HOST_ACTORS: frozenset[str] = frozenset(
    {"host", "host-agent", "host_agent", "agent", "swarm", "loop", "evolver"}
)
_HOST_ACTOR_PREFIXES: tuple[str, ...] = ("host", "agent", "swarm", "loop", "evolver")

#: Gate decision persisted next to the run (§5.2): the session's Accept is an
#: echo of a real ``accept: true`` gate decision, never a bare claim.
GATE_FILENAME: str = "gate.json"

_RUN_DIR_RE = re.compile(r"^run_(\d+)$")


class EvolutionError(RuntimeError):
    """A session lifecycle rule would be violated."""


class EvolutionBudgetExhaustedError(EvolutionError):
    """A new round was requested after the frozen budget was spent."""


class EvolutionTerminalError(EvolutionError):
    """A running-only action was attempted on an ended session."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def session_root() -> Path:
    """Session root, outside the product repo.

    ``EVOLUTION_DIR`` wins (the soak interlock already points it out of the git
    tree); otherwise fall back to ``soak_root()/evolution``. Same source as
    :mod:`evolver.ops.soak_env`.
    """
    env = os.environ.get("EVOLUTION_DIR")
    base = Path(env).expanduser() if env else soak_root() / "evolution"
    return base / SESSION_SUBDIR


def _active_library_snapshot() -> str | None:
    """The library version a session starts from (charter §5.4).

    Frozen at open, so a snapshot published mid-comparison cannot quietly
    become the thing the Parent is measured against: during a comparison
    ``active`` still points at the Parent, and the run remembers which one
    that was.
    """
    try:
        from evolver.gep.library import active_snapshot_id

        return active_snapshot_id()
    except Exception:
        return None


def _advance_cursor(recorded_at: str, run_id: str) -> dict[str, Any]:
    """Move the evolution cursor forward — the Accept is the only writer.

    A Reject consumes nothing: the same external experience stays available
    to the next Candidate, because "not yet understood" is not "consumed"
    (charter §5.5). Failure here is observation loss, never a reason to
    withhold an already-earned Accept.
    """
    try:
        from evolver.gep.cursor import advance

        result = advance(recorded_at=recorded_at, session_id=run_id)
    except Exception:
        return {"ok": False, "reason": "cursor_unavailable"}
    return dict(result)


class EvolutionSession:
    """State, budget, and publication control for one evolution session."""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        project_root: Path | str | None = None,
    ) -> None:
        # project_root is reserved for workspace resolution; unused for now.
        del project_root
        self._root = Path(root).expanduser() if root else session_root()
        self._run: dict[str, Any] | None = None

    # ---- layout -----------------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    def _run_dir_for(self, run_id: str) -> Path:
        return self._root / run_id

    @property
    def run_dir(self) -> Path:
        return self._run_dir_for(str(self._require_run()["run_id"]))

    # ---- session lifecycle ------------------------------------------------

    def start_run(
        self,
        parent: str,
        *,
        adapter: str = "",
        max_rounds: int | None = None,
        acceptance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Open a new session; the round budget freezes at the charter value.

        ``max_rounds`` is accepted-but-refused (kept in the signature so a
        caller that still tries it learns why): §5.1 freezes the opening
        budget at :data:`DEFAULT_MAX_ROUNDS`, and only a named human may
        raise it afterwards via :meth:`extend_budget`. Refused while another
        session is running - resume that one instead.
        """
        if not str(parent or "").strip():
            raise ValueError("parent is required")
        running = self.latest_run()
        if running is not None and running.get("status") == RUNNING:
            raise EvolutionError(f"Run {running['run_id']} is still running; resume it instead")

        run_id = f"run_{self._next_run_number()}"
        budget = self._resolve_budget(max_rounds)
        run: dict[str, Any] = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "status": RUNNING,
            "parent": str(parent),
            # §5.4 — frozen at open. During the comparison ``active`` still
            # points at the Parent; this id is what proves which one that was.
            "parent_snapshot": _active_library_snapshot(),
            "adapter": str(adapter or ""),
            "acceptance": acceptance or {},
            "budget": {"max_rounds": budget},
            "budget_history": [{"max_rounds": budget, "confirmed_by": "start", "at": _now()}],
            "min_rejects_before_incomplete": DEFAULT_MIN_REJECTS_BEFORE_INCOMPLETE,
            "round": 0,
            "current_hypothesis": "",
            "current_candidate": "",
            "accepted_ref": "",
            "end_reason": "",
            "created_at": _now(),
            "updated_at": _now(),
        }
        self._run_dir_for(run_id).mkdir(parents=True, exist_ok=True)
        self._run = run
        self._save_run()
        return dict(run)

    def resume(self, run_id: str | None = None) -> dict[str, Any]:
        """Resume the running session, reusing its frozen budget.

        An ended session cannot be reopened - start a new run instead.
        """
        run = self._load_run(run_id) if run_id else self.latest_run()
        if run is None:
            raise EvolutionError("No evolution session found to resume")
        if run.get("status") != RUNNING:
            raise EvolutionTerminalError(
                f"Run {run.get('run_id')} already ended with status "
                f"{run.get('status')!r}; start a new run instead"
            )
        self._run = run
        return dict(run)

    def latest_run(self) -> dict[str, Any] | None:
        """Most recent session record, or ``None`` when none exists."""
        if not self._root.is_dir():
            return None
        numbers = [
            int(match.group(1))
            for child in self._root.iterdir()
            if (match := _RUN_DIR_RE.match(child.name)) and child.is_dir()
        ]
        if not numbers:
            return None
        return self._load_run(f"run_{max(numbers)}")

    def finalize(self) -> dict[str, Any]:
        """Last guard before reporting: a running session may not be final."""
        run = self._require_run()
        if run["status"] == RUNNING:
            raise EvolutionError(
                "Run is still running; accept a Candidate or mark the run "
                "incomplete before finalizing"
            )
        return dict(run)

    # ---- rounds -----------------------------------------------------------

    def begin_round(self, hypothesis: str, candidate: str) -> int:
        """Open the next round for one formal Candidate.

        When the frozen budget is spent the session closes itself as
        ``incomplete / budget_exhausted`` and the caller gets an exception.
        """
        run = self._require_running()
        if not str(candidate or "").strip():
            raise ValueError("candidate is required")
        if run["round"] >= int(run["budget"]["max_rounds"]):
            self.mark_incomplete("budget_exhausted")
            raise EvolutionBudgetExhaustedError(
                f"Budget exhausted after {run['round']} rounds; extend the "
                "budget (with human confirmation) or end the run"
            )
        run["round"] += 1
        run["current_hypothesis"] = str(hypothesis or "")
        run["current_candidate"] = str(candidate)
        self._save_run()
        return int(run["round"])

    def rejected_count(self) -> int:
        """Formally rejected Candidates in this session so far."""
        path = self.run_dir / "rounds.jsonl"
        if not path.is_file():
            return 0
        rejected = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("decision") == "reject":
                rejected += 1
        return rejected

    def must_continue(self) -> bool:
        """True while the session still needs another Candidate."""
        return self._require_run().get("status") == RUNNING

    def record_round(
        self,
        *,
        decision: str = "reject",
        metrics: dict[str, Any] | None = None,
        artifact_refs: list[str] | None = None,
        notes: str = "",
        cycle_ref: str = "",
    ) -> dict[str, Any]:
        """Append the finished round to ``rounds.jsonl``. Rejects only.

        Acceptance flows through :meth:`accept` so publication and the state
        change stay atomic. A Reject leaves the session ``running``.
        ``cycle_ref`` is the swarm cycle this round came from — the key
        :meth:`has_round_for` uses so a retried solidify cannot burn a
        second round on the same Candidate.
        """
        if decision != "reject":
            raise ValueError(
                "record_round only records rejects; use accept() or "
                "mark_incomplete() for the other outcomes"
            )
        run = self._require_running()
        entry = {
            "round": int(run["round"]),
            "hypothesis": run.get("current_hypothesis", ""),
            "candidate": run.get("current_candidate", ""),
            "metrics": metrics or {},
            "decision": decision,
            "artifact_refs": list(artifact_refs or []),
            "notes": str(notes or ""),
            "cycle_ref": str(cycle_ref or ""),
            "recorded_at": _now(),
        }
        rounds_path = self.run_dir / "rounds.jsonl"
        rounds_path.parent.mkdir(parents=True, exist_ok=True)
        with rounds_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._save_run()
        return entry

    def has_round_for(self, cycle_ref: str) -> bool:
        """Whether this swarm cycle has already been folded into the ledger.

        One Candidate, one round — no matter how many times solidify runs on
        the same pending state. Without this check a retried refusal would
        spend the budget twice for one measurement.
        """
        ref = str(cycle_ref or "").strip()
        if not ref:
            return False
        path = self.run_dir / "rounds.jsonl"
        if not path.is_file():
            return False
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(entry.get("cycle_ref") or "") == ref:
                return True
        return False

    def extend_budget(self, max_rounds: int, *, confirmed_by: str) -> dict[str, Any]:
        """Raise the frozen round budget - human only, and on the record.

        Host-side actors (``host`` / ``agent`` / ``swarm`` / ``loop``) are
        refused. Every raise lands in ``budget_history`` for audit.
        """
        run = self._require_running()
        actor = str(confirmed_by or "").strip()
        if not actor:
            raise EvolutionError("extend_budget requires a non-empty confirmed_by")
        lowered = actor.lower()
        if lowered in HOST_ACTORS or lowered.startswith(_HOST_ACTOR_PREFIXES):
            raise EvolutionError(f"extend_budget is human-only; refused actor {actor!r}")
        new_budget = int(max_rounds)
        if new_budget <= int(run["budget"]["max_rounds"]):
            raise ValueError(
                f"extend_budget must increase max_rounds (current: {run['budget']['max_rounds']})"
            )
        run["budget"]["max_rounds"] = new_budget
        history = run.get("budget_history")
        if not isinstance(history, list):
            history = []
            run["budget_history"] = history
        history.append({"max_rounds": new_budget, "confirmed_by": actor, "at": _now()})
        self._save_run()
        return dict(run)

    # ---- evaluations ------------------------------------------------------

    def record_evaluation(
        self,
        subject: str,
        result: dict[str, Any],
        *,
        role: str = "",
    ) -> Path:
        """Persist a stable summary of a formal Parent/Candidate evaluation.

        Raw artifacts stay where they are; only the summary and path refs come
        into the run.
        """
        run = self._require_run()
        summary = {
            "subject": str(subject),
            "role": str(role or ""),
            "round": int(run["round"]),
            "metrics": result.get("metrics", {}),
            "cases": result.get("cases", []),
            "artifact_paths": result.get("artifact_paths", []),
            "provenance": result.get("provenance", "unspecified"),
            "gate_input": result.get("gate_input"),
            "recorded_at": _now(),
        }
        evaluations_dir = self.run_dir / "evaluations"
        evaluations_dir.mkdir(parents=True, exist_ok=True)
        safe_subject = re.sub(r"[^A-Za-z0-9._-]+", "_", str(subject)).strip("_") or "subject"
        safe_role = re.sub(r"[^A-Za-z0-9._-]+", "_", str(role)).strip("_")
        name = f"round{summary['round']}"
        if safe_role:
            name += f"_{safe_role}"
        path = evaluations_dir / f"{name}_{safe_subject}.json"
        _write_json_atomic(path, summary)
        return path

    # ---- decision ---------------------------------------------------------

    def accept(
        self,
        *,
        gate: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        publish: Callable[[str], str] | None = None,
    ) -> str:
        """Accept the current Candidate: gate, publish, switch to accepted.

        Charter §5.2/§5.3 — an Accept exists only when the publication gate
        actually passed. ``gate`` is injected by the caller; without one the
        session falls back to the decision solidify persisted
        (:meth:`record_gate_decision`), and if that is missing or refusing
        the Accept is refused — a bare ``accept`` command is a claim, not a
        measurement. ``publish`` returns the published version id (batch C
        wires the library snapshot); without a publisher the Candidate ref is
        kept.
        """
        run = self._require_running()
        candidate = str(run.get("current_candidate") or "")
        if not candidate:
            raise EvolutionError("No Candidate under evaluation to accept")
        decision = gate(run) if gate is not None else self.pending_gate()
        if not isinstance(decision, dict) or not decision.get("accept"):
            detail = ""
            if isinstance(decision, dict) and decision.get("reason"):
                detail = f" (last gate reason: {decision.get('reason')})"
            elif decision is None:
                detail = " (no gate decision recorded — run solidify first)"
            raise EvolutionError(
                "Candidate did not pass the publication gate — the session "
                f"cannot Accept without an accept:true gate record{detail}"
            )
        run["gate"] = decision
        published = publish(candidate) if publish is not None else candidate
        accepted_at = _now()
        run["status"] = ACCEPTED
        run["accepted_ref"] = str(published)
        run["end_reason"] = ""
        run["accepted_at"] = accepted_at
        # §5.5 — the Accept is the only thing that consumes external
        # experience. A Reject or an exhausted budget leaves the cursor
        # where it was: not yet understood is not yet consumed.
        run["cursor"] = _advance_cursor(accepted_at, str(run.get("run_id") or ""))
        self._save_run()
        return str(published)

    def mark_incomplete(self, reason: str) -> dict[str, Any]:
        """Stop for an external reason: no publish, no checkpoint advance.

        Reject and ordinary stagnation are not reasons. Judgment reasons
        (missing data / unreliable evaluation / external block) are refused
        until enough Candidates have been rejected - "no new hypothesis yet"
        is not "cannot continue".
        """
        run = self._require_running()
        normalized = str(reason or "").strip()
        if normalized not in INCOMPLETE_REASONS:
            raise ValueError(f"incomplete reason must be one of {sorted(INCOMPLETE_REASONS)}")
        if normalized in JUDGMENT_STOP_REASONS:
            required = int(
                run.get("min_rejects_before_incomplete", DEFAULT_MIN_REJECTS_BEFORE_INCOMPLETE)
            )
            seen = self.rejected_count()
            if seen < required:
                raise EvolutionError(
                    f"Cannot stop for {normalized!r}: the run is still running and has "
                    f"{seen} rejected candidate(s); at least {required} rejected "
                    "candidates are required before this external stop is allowed. "
                    "Design and evaluate the next Candidate in this run instead."
                )
        if normalized == "budget_exhausted" and run["round"] < int(run["budget"]["max_rounds"]):
            raise EvolutionError(
                "Cannot stop for budget_exhausted: the round budget has not been spent "
                "yet. Continue the loop; begin_round raises EvolutionBudgetExhaustedError "
                "automatically when the budget is spent."
            )
        run["status"] = INCOMPLETE
        run["end_reason"] = normalized
        self._save_run()
        return dict(run)

    # ---- accessors --------------------------------------------------------

    @property
    def run(self) -> dict[str, Any]:
        return dict(self._require_run())

    @property
    def run_id(self) -> str:
        return str(self._require_run()["run_id"])

    @property
    def status(self) -> str:
        return str(self._require_run()["status"])

    # ---- internals --------------------------------------------------------

    def _next_run_number(self) -> int:
        latest = self.latest_run()
        if latest is None:
            return 1
        match = _RUN_DIR_RE.match(str(latest.get("run_id", "")))
        return int(match.group(1)) + 1 if match else 1

    def _load_run(self, run_id: str) -> dict[str, Any] | None:
        path = self._run_dir_for(run_id) / "run.json"
        if not path.is_file():
            return None
        run = _read_json(path)
        if not isinstance(run, dict) or run.get("run_id") != run_id:
            raise EvolutionError(f"Corrupt run record: {path}")
        return run

    def _require_run(self) -> dict[str, Any]:
        if self._run is None:
            run = self.latest_run()
            if run is None:
                raise EvolutionError("No evolution session loaded; start or resume one")
            self._run = run
        return self._run

    def _require_running(self) -> dict[str, Any]:
        run = self._require_run()
        if run.get("status") != RUNNING:
            raise EvolutionTerminalError(
                f"Run {run.get('run_id')} is {run.get('status')!r}; only a running run can continue"
            )
        return run

    def _save_run(self) -> None:
        run = self._require_run()
        run["updated_at"] = _now()
        _write_json_atomic(self.run_dir / "run.json", run)

    def _resolve_budget(self, max_rounds: int | None) -> int:
        """The opening budget is frozen at the charter value (§5.1).

        ``start_run`` accepts no override any more: a host that could pick its
        own budget at open could also pick a long enough one to outlast
        scrutiny. Raising the bar is the named human's move, via
        :meth:`extend_budget`, and it lands in ``budget_history``.
        """
        if max_rounds is not None:
            raise EvolutionError(
                "the opening budget is frozen at "
                f"{DEFAULT_MAX_ROUNDS} (§5.1) — `session start` takes no "
                "budget override; a human raises it with `session extend`"
            )
        return DEFAULT_MAX_ROUNDS

    # ---- gate ledger (§5.2) ----------------------------------------------

    def record_gate_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        """Persist the latest publication-gate decision next to the run.

        Written by solidify on every cycle — accept or refuse — so a stale
        ``accept: true`` from a previous round can never clear a later bar.
        """
        self._require_running()
        if not isinstance(decision, dict):
            raise ValueError("gate decision must be a JSON object")
        payload = dict(decision)
        payload.setdefault("accept", False)
        payload["recorded_at"] = _now()
        _write_json_atomic(self.run_dir / GATE_FILENAME, payload)
        return payload

    def pending_gate(self) -> dict[str, Any] | None:
        """The latest persisted gate decision, or ``None`` when there is none."""
        run = self._require_run()
        path = self._run_dir_for(str(run["run_id"])) / GATE_FILENAME
        if not path.is_file():
            return None
        try:
            payload = _read_json(path)
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None


def latest_session(root: Path | str | None = None) -> dict[str, Any] | None:
    """Most recent session record (convenience entry for CLI / loop)."""
    return EvolutionSession(root).latest_run()


def active_session(root: Path | str | None = None) -> dict[str, Any] | None:
    """The running session, or ``None`` when there is none."""
    run = latest_session(root)
    return run if run is not None and run.get("status") == RUNNING else None


__all__ = [
    "ACCEPTED",
    "DEFAULT_MAX_ROUNDS",
    "DEFAULT_MIN_REJECTS_BEFORE_INCOMPLETE",
    "GATE_FILENAME",
    "HOST_ACTORS",
    "IMMEDIATE_STOP_REASONS",
    "INCOMPLETE",
    "INCOMPLETE_REASONS",
    "JUDGMENT_STOP_REASONS",
    "RUNNING",
    "RUN_SCHEMA_VERSION",
    "SESSION_SUBDIR",
    "TERMINAL_STATES",
    "EvolutionBudgetExhaustedError",
    "EvolutionError",
    "EvolutionSession",
    "EvolutionTerminalError",
    "active_session",
    "latest_session",
    "session_root",
]
