"""Sprint 24.10: durable workflow engine — DSL, WAL, approval gates, retry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep.workflow import (
    MAX_ATTEMPTS,
    ST_DONE,
    ST_FAILED,
    ST_RETRY_WAIT,
    ST_WAITING_AGENT,
    ST_WAITING_APPROVAL,
    WorkflowEngine,
    WorkflowPermanentError,
    WorkflowTransientError,
)


def _engine(tmp: Path, **kw) -> WorkflowEngine:
    return WorkflowEngine(workflows_dir=tmp / "workflows", now=1_000.0, **kw)


def _spec(*steps: dict[str, object], **extra: object) -> dict[str, object]:
    return {"id": "wf1", "steps": list(steps), **extra}


class TestScriptSteps:
    def test_happy_path(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace, core_calls={"add": lambda a, b: a + b})
        state = engine.create(_spec({"kind": "script", "name": "add", "args": {"a": 2, "b": 3}}))
        engine.run(state)
        assert state.status == ST_DONE
        assert state.variables["_last_result"] == 5
        assert state.step_index == 1

    def test_unknown_call_is_permanent(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace)
        state = engine.create(_spec({"kind": "script", "name": "nope"}))
        engine.run(state)
        assert state.status == ST_FAILED
        assert "unknown core call" in (state.error or "")

    def test_non_json_args_rejected(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace)
        with pytest.raises(WorkflowPermanentError, match="non-JSON value"):
            engine.create(_spec({"kind": "script", "name": "echo", "args": {"bad": object()}}))


class TestControlFlow:
    def test_foreach_sequential(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace, core_calls={"collect": lambda x: f"got-{x}"})
        state = engine.create(
            _spec(
                {
                    "kind": "foreach",
                    "items": ["a", "b", "c"],
                    "steps": [{"kind": "script", "name": "collect", "args": {"x": "item"}}],
                }
            )
        )
        engine.run(state)
        assert state.status == ST_DONE

    def test_foreach_variable_source(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace)
        state = engine.create(
            _spec(
                {
                    "kind": "foreach",
                    "items": "items",
                    "steps": [{"kind": "script", "name": "noop"}],
                }
            )
        )
        state.variables["items"] = [1, 2]
        engine.run(state)
        assert state.status == ST_DONE

    def test_if_branch(self, temp_workspace: Path) -> None:
        engine = _engine(
            temp_workspace,
            predicates={"flag": lambda flag: flag},
        )
        state = engine.create(
            _spec(
                {
                    "kind": "if",
                    "predicate": "flag",
                    "args": {"flag": True},
                    "then": [{"kind": "script", "name": "noop"}],
                    "else": [],
                }
            )
        )
        engine.run(state)
        assert state.status == ST_DONE

    def test_unknown_predicate_permanent(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace)
        state = engine.create(_spec({"kind": "if", "predicate": "wat"}))
        engine.run(state)
        assert state.status == ST_FAILED
        assert "unknown predicate" in (state.error or "")


class TestApprovalGate:
    def test_pause_approve_resume(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace)
        state = engine.create(
            _spec(
                {"kind": "script", "name": "noop"},
                {"kind": "approval"},
                {"kind": "script", "name": "noop"},
            )
        )
        engine.run(state)
        assert state.status == ST_WAITING_APPROVAL
        assert state.step_index == 1

        state = engine.approve("wf1", note="go")
        assert state.status == ST_DONE
        assert state.step_index == 3

    def test_reject_fails_run(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace)
        state = engine.create(_spec({"kind": "approval"}))
        engine.run(state)
        state = engine.reject("wf1", note="no way")
        assert state.status == ST_FAILED
        assert "no way" in (state.error or "")

    def test_approve_on_wrong_state_rejected(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace)
        state = engine.create(_spec({"kind": "script", "name": "noop"}))
        engine.run(state)
        with pytest.raises(WorkflowPermanentError):
            engine.approve("wf1")


class TestRetryAndAgent:
    def test_transient_retries_then_succeeds(self, temp_workspace: Path) -> None:
        attempts = {"n": 0}

        def flaky() -> None:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise WorkflowTransientError("blip")

        engine = _engine(temp_workspace, core_calls={"flaky": flaky})
        state = engine.create(_spec({"kind": "script", "name": "flaky"}))
        engine.run(state)
        assert state.status == ST_RETRY_WAIT
        assert state.attempts == 1
        assert state.retry_at is not None

        state = engine.resume("wf1")
        assert state.status == ST_RETRY_WAIT  # attempt 2 also fails
        state = engine.resume("wf1")
        assert state.status == ST_DONE
        assert attempts["n"] == 3

    def test_exhausted_retries_fail(self, temp_workspace: Path) -> None:
        engine = _engine(
            temp_workspace,
            core_calls={"boom": lambda: (_ for _ in ()).throw(WorkflowTransientError("x"))},
        )
        state = engine.create(_spec({"kind": "script", "name": "boom"}))
        for _ in range(MAX_ATTEMPTS):
            state = engine.resume("wf1") if state.status == ST_RETRY_WAIT else engine.run(state)
        assert state.status == ST_FAILED

    def test_agent_wait_complete(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace)
        state = engine.create(
            _spec(
                {"kind": "agent", "payload": {"prompt": "do it"}},
                {"kind": "script", "name": "noop"},
            )
        )
        engine.run(state)
        assert state.status == ST_WAITING_AGENT

        state = engine.complete_agent("wf1", {"ok": True})
        assert state.status == ST_DONE
        assert state.variables["_agent_result"] == {"ok": True}


class TestPersistence:
    def test_crash_resume_from_checkpoint(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace, core_calls={"noop": lambda: None})
        state = engine.create(
            _spec(
                {"kind": "script", "name": "noop"},
                {"kind": "script", "name": "noop"},
                {"kind": "approval"},
            )
        )
        engine.run(state)
        assert state.status == ST_WAITING_APPROVAL
        assert state.step_index == 2

        # Simulated crash: a NEW engine loads the snapshot and resumes.
        engine2 = _engine(temp_workspace)
        loaded = engine2.load("wf1")
        assert loaded.step_index == 2
        state = engine2.approve("wf1")
        assert state.status == ST_DONE

    def test_wal_events_recorded(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace)
        state = engine.create(_spec({"kind": "approval"}))
        engine.run(state)
        wal = (
            (temp_workspace / "workflows" / "wf1.wal.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        events = [json.loads(line)["event"] for line in wal]
        assert events == ["created", "started", "waiting_approval"]

    def test_cancel(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace)
        state = engine.create(_spec({"kind": "approval"}))
        engine.run(state)
        state = engine.cancel("wf1")
        assert state.status == "cancelled"
