"""Durable workflow engine — declarative DSL, WAL history, approval gates.

Concept harvest from Node v2 ``workflow/{dsl,runtime,stateStore}.d.ts``
(behavioral re-implementation; no code copied; thin slice).

Steps (structural args only — no eval):
- ``script``   whitelisted named core call with JSON-ish args
- ``foreach``  sequential iteration over a literal list or stored variable
- ``if``       whitelisted named predicate → ``then`` / ``else`` branches
- ``agent``    external payload; waits for ``complete_agent`` (like approval)
- ``approval`` durable human gate; ``approve`` / ``reject`` are the only exits

Durability: append-only history JSONL (WAL) + atomic state snapshot after
every step, so a crashed run resumes from its step index. Transient step
errors retry with exponential backoff (``retry_wait``); permanent errors
fail the run. ``script`` steps default to idempotent-by-index: re-running a
step after a crash re-executes it, so core calls must tolerate at-least-once.

Sprint 24.10 (演进方案.md §9 概念收割 #9 — thin slice).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

WORKFLOWS_DIRNAME = "workflows"
MAX_STEPS: int = 256
MAX_DEPTH: int = 16
MAX_ATTEMPTS: int = 3
BACKOFF_BASE_S: float = 2.0

ST_PENDING = "pending"
ST_RUNNING = "running"
ST_WAITING_APPROVAL = "waiting_approval"
ST_WAITING_AGENT = "waiting_agent"
ST_RETRY_WAIT = "retry_wait"
ST_DONE = "done"
ST_FAILED = "failed"
ST_CANCELLED = "cancelled"

TERMINAL_STATUSES: frozenset[str] = frozenset({ST_DONE, ST_FAILED, ST_CANCELLED})

_JSON_SCALARS = (str, int, float, bool)


class WorkflowTransientError(Exception):
    """Step failed but may succeed on retry (network blips, locks)."""


class WorkflowPermanentError(Exception):
    """Step failed and retrying cannot help."""


def _validate_args(args: Any, path: str = "args") -> None:
    if isinstance(args, _JSON_SCALARS) or args is None:
        return
    if isinstance(args, list):
        for i, item in enumerate(args):
            _validate_args(item, f"{path}[{i}]")
        return
    if isinstance(args, dict):
        for key, value in args.items():
            if not isinstance(key, str):
                raise WorkflowPermanentError(f"{path}: non-string key {key!r}")
            _validate_args(value, f"{path}.{key}")
        return
    raise WorkflowPermanentError(f"{path}: non-JSON value {type(args).__name__}")


@dataclass
class WorkflowState:
    id: str
    spec: dict[str, Any]
    status: str = ST_PENDING
    step_index: int = 0
    attempts: int = 0
    variables: dict[str, Any] = field(default_factory=dict)
    depth: int = 0
    error: str | None = None
    retry_at: float | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "spec": self.spec,
            "status": self.status,
            "step_index": self.step_index,
            "attempts": self.attempts,
            "variables": self.variables,
            "depth": self.depth,
            "error": self.error,
            "retry_at": self.retry_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _default_registry() -> dict[str, Callable[..., Any]]:
    return {
        "noop": lambda **kw: None,
        "echo": lambda **kw: kw,
    }


def _default_predicates() -> dict[str, Callable[..., bool]]:
    return {
        "true": lambda **kw: True,
        "var_truthy": lambda name, **kw: bool(kw.get("variables", {}).get(name)),
    }


class WorkflowEngine:
    """Durable multi-step workflow runner (M4B thin slice)."""

    def __init__(
        self,
        *,
        workflows_dir: Path | None = None,
        core_calls: dict[str, Callable[..., Any]] | None = None,
        predicates: dict[str, Callable[..., bool]] | None = None,
        now: float | None = None,
    ) -> None:
        if workflows_dir is None:
            from evolver.gep.paths import get_evolution_dir

            workflows_dir = get_evolution_dir() / WORKFLOWS_DIRNAME
        self.dir = workflows_dir
        self.core_calls = dict(_default_registry(), **(core_calls or {}))
        self.predicates = dict(_default_predicates(), **(predicates or {}))
        self._now = now

    # -- persistence --------------------------------------------------------

    def _state_path(self, workflow_id: str) -> Path:
        return self.dir / f"{workflow_id}.json"

    def _wal_path(self, workflow_id: str) -> Path:
        return self.dir / f"{workflow_id}.wal.jsonl"

    def _save(self, state: WorkflowState, *, event: dict[str, Any] | None = None) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        if event is not None:
            with open(self._wal_path(state.id), "a", encoding="utf-8") as f:
                f.write(
                    json.dumps({"ts": self._now or time.time(), **event}, ensure_ascii=False) + "\n"
                )
        state.updated_at = self._now or time.time()
        path = self._state_path(state.id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state.to_dict(), ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    # -- public verbs -------------------------------------------------------

    def create(self, spec: dict[str, Any]) -> WorkflowState:
        steps = spec.get("steps")
        if not isinstance(steps, list) or not steps:
            raise WorkflowPermanentError("spec.steps must be a non-empty list")
        if len(steps) > MAX_STEPS:
            raise WorkflowPermanentError(f"too many steps (> {MAX_STEPS})")
        # Spec must be structurally JSON from the start (v2: structural args).
        _validate_args(steps, "steps")
        state = WorkflowState(id=spec.get("id") or uuid.uuid4().hex[:12], spec=spec)
        self._save(state, event={"event": "created"})
        return state

    def load(self, workflow_id: str) -> WorkflowState:
        try:
            raw = json.loads(self._state_path(workflow_id).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LookupError(f"workflow not found: {workflow_id}") from exc
        state = WorkflowState(id=workflow_id, spec=dict(raw.get("spec") or {"steps": []}))
        state.status = str(raw["status"])
        state.step_index = int(raw["step_index"])
        state.attempts = int(raw["attempts"])
        state.variables = dict(raw.get("variables") or {})
        state.depth = int(raw.get("depth", 0))
        state.error = raw.get("error")
        state.retry_at = raw.get("retry_at")
        state.created_at = float(raw["created_at"])
        state.updated_at = float(raw["updated_at"])
        return state

    def run(self, state: WorkflowState) -> WorkflowState:
        """Advance until wait/done/failed — returns the new state."""
        while state.status not in TERMINAL_STATUSES | {
            ST_WAITING_APPROVAL,
            ST_WAITING_AGENT,
            ST_RETRY_WAIT,
        }:
            state = self._step(state)
        return state

    def resume(self, workflow_id: str) -> WorkflowState:
        state = self.load(workflow_id)
        if state.status not in (ST_RETRY_WAIT, ST_WAITING_AGENT, ST_PENDING, ST_RUNNING):
            raise WorkflowPermanentError(f"cannot resume from {state.status}")
        if state.status == ST_RETRY_WAIT:
            state.status = ST_RUNNING
            self._save(state, event={"event": "resumed"})
        return self.run(state)

    def approve(self, workflow_id: str, *, note: str | None = None) -> WorkflowState:
        state = self.load(workflow_id)
        if state.status != ST_WAITING_APPROVAL:
            raise WorkflowPermanentError(f"not waiting for approval: {state.status}")
        state.status = ST_RUNNING
        state.step_index += 1
        state.attempts = 0
        self._save(
            state,
            event={"event": "approved", "note": note, "step": state.step_index - 1},
        )
        return self.run(state)

    def reject(self, workflow_id: str, *, note: str | None = None) -> WorkflowState:
        state = self.load(workflow_id)
        if state.status != ST_WAITING_APPROVAL:
            raise WorkflowPermanentError(f"not waiting for approval: {state.status}")
        state.status = ST_FAILED
        state.error = f"rejected: {note or 'no note'}"
        self._save(state, event={"event": "rejected", "note": note})
        return state

    def cancel(self, workflow_id: str) -> WorkflowState:
        state = self.load(workflow_id)
        if state.status in TERMINAL_STATUSES:
            return state
        state.status = ST_CANCELLED
        self._save(state, event={"event": "cancelled"})
        return state

    def complete_agent(self, workflow_id: str, result: Any) -> WorkflowState:
        state = self.load(workflow_id)
        if state.status != ST_WAITING_AGENT:
            raise WorkflowPermanentError(f"not waiting for agent: {state.status}")
        state.variables["_agent_result"] = result
        state.status = ST_RUNNING
        state.step_index += 1
        state.attempts = 0
        self._save(state, event={"event": "agent_completed"})
        return self.run(state)

    def status(self, workflow_id: str) -> dict[str, Any]:
        state = self.load(workflow_id)
        return state.to_dict()

    # -- step machine -------------------------------------------------------

    def _step(self, state: WorkflowState) -> WorkflowState:
        if state.status == ST_PENDING:
            state.status = ST_RUNNING
            self._save(state, event={"event": "started"})
            return state
        steps = state.spec["steps"]
        if state.step_index >= len(steps):
            state.status = ST_DONE
            self._save(state, event={"event": "done"})
            return state
        if state.depth >= MAX_DEPTH:
            state.status = ST_FAILED
            state.error = "max depth exceeded"
            self._save(state, event={"event": "failed", "error": state.error})
            return state

        step = steps[state.step_index]
        paused = False
        try:
            paused = bool(self._execute_step(state, step))
        except WorkflowTransientError as exc:
            state.attempts += 1
            if state.attempts >= MAX_ATTEMPTS:
                state.status = ST_FAILED
                state.error = str(exc)
                self._save(state, event={"event": "failed", "error": state.error})
            else:
                state.status = ST_RETRY_WAIT
                state.retry_at = (self._now or time.time()) + BACKOFF_BASE_S**state.attempts
                self._save(state, event={"event": "retry", "error": str(exc)})
            return state
        except WorkflowPermanentError as exc:
            state.status = ST_FAILED
            state.error = str(exc)
            self._save(state, event={"event": "failed", "error": state.error})
            return state

        if paused:
            return state  # waiting_approval / waiting_agent — already saved

        state.attempts = 0
        state.step_index += 1
        self._save(state, event={"event": "step_done", "step": state.step_index - 1})
        return state

    def _execute_step(self, state: WorkflowState, step: dict[str, Any]) -> bool:
        """Run one step; returns True when it parked the run (waiting)."""
        kind = step.get("kind")
        if kind == "script":
            name = step.get("name")
            if name not in self.core_calls:
                raise WorkflowPermanentError(f"unknown core call: {name}")
            args = step.get("args", {})
            _validate_args(args)
            result = self.core_calls[name](**args)
            state.variables["_last_result"] = result
        elif kind == "foreach":
            items = step.get("items")
            if isinstance(items, str):
                items = state.variables.get(items)
            if not isinstance(items, list):
                raise WorkflowPermanentError("foreach.items must be a list or variable name")
            for item in items:
                self._run_substeps(state, step.get("steps", []), item)
        elif kind == "if":
            pred = step.get("predicate")
            if pred not in self.predicates:
                raise WorkflowPermanentError(f"unknown predicate: {pred}")
            args = step.get("args", {})
            _validate_args(args)
            branch = "then" if self.predicates[pred](**args) else "else"
            self._run_substeps(state, step.get(branch, []), None)
        elif kind == "approval":
            state.status = ST_WAITING_APPROVAL
            self._save(state, event={"event": "waiting_approval", "step": state.step_index})
            return True
        elif kind == "agent":
            state.status = ST_WAITING_AGENT
            self._save(
                state,
                event={"event": "waiting_agent", "step": state.step_index},
            )
            return True
        else:
            raise WorkflowPermanentError(f"unknown step kind: {kind}")
        return False

    def _run_substeps(self, state: WorkflowState, steps: list[dict[str, Any]], item: Any) -> None:
        if state.depth + 1 >= MAX_DEPTH:
            raise WorkflowPermanentError("max depth exceeded")
        state.depth += 1
        try:
            for sub in steps:
                self._execute_step(state, sub)
        finally:
            state.depth -= 1


__all__ = [
    "BACKOFF_BASE_S",
    "MAX_ATTEMPTS",
    "MAX_DEPTH",
    "MAX_STEPS",
    "TERMINAL_STATUSES",
    "WorkflowEngine",
    "WorkflowPermanentError",
    "WorkflowState",
    "WorkflowTransientError",
]
