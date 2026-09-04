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


# ---------------------------------------------------------------------------
# v1.110.0 — EvoX harvest: YAML specs, templates, agent roles, gate steps
# ---------------------------------------------------------------------------


class TestYamlSpecs:
    def test_yaml_round_trip(self, temp_workspace: Path) -> None:
        from evolver.gep.workflow import dump_spec_yaml, load_spec

        spec = _spec({"kind": "script", "name": "echo", "args": {"x": 1}})
        path = dump_spec_yaml(spec, temp_workspace / "wf.yaml")
        assert load_spec(path) == spec

    def test_load_spec_rejects_non_mapping(self, temp_workspace: Path) -> None:
        from evolver.gep.workflow import load_spec

        path = temp_workspace / "bad.yaml"
        path.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(WorkflowPermanentError):
            load_spec(path)

    def test_json_spec_still_loads(self, temp_workspace: Path) -> None:
        from evolver.gep.workflow import load_spec

        path = temp_workspace / "wf.json"
        path.write_text(json.dumps(_spec({"kind": "script", "name": "noop"})), encoding="utf-8")
        assert load_spec(path)["id"] == "wf1"


class TestTemplates:
    def test_bundled_templates_load_and_validate(self, temp_workspace: Path) -> None:
        from evolver.gep.workflow import list_templates, load_template

        names = list_templates()
        assert "repair" in names
        assert "innovate" in names
        for name in names:
            spec = load_template(name)
            state = _engine(temp_workspace).create(spec)  # create() validates
            assert state.id

    def test_unknown_template(self) -> None:
        from evolver.gep.workflow import load_template

        with pytest.raises(FileNotFoundError):
            load_template("does-not-exist")


def _gate(ok: bool) -> dict[str, object]:
    return {"overall_ok": ok, "stages": [], "failed_stages": [] if ok else ["mypy"]}


class TestGateStep:
    def test_gate_pass_records_verdict(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace, cascade_runner=lambda: _gate(True))
        state = engine.create(_spec({"kind": "gate"}))
        engine.run(state)
        assert state.status == ST_DONE
        assert state.variables["_gate_verdict"]["overall_ok"] is True

    def test_gate_fail_fails_run(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace, cascade_runner=lambda: _gate(False))
        state = engine.create(_spec({"kind": "gate"}))
        engine.run(state)
        assert state.status == ST_FAILED
        assert "gate failed" in (state.error or "")

    def test_gate_on_fail_skip_continues(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace, cascade_runner=lambda: _gate(False))
        state = engine.create(_spec({"kind": "gate", "on_fail": "skip"}))
        engine.run(state)
        assert state.status == ST_DONE
        assert state.variables["_gate_verdict"]["overall_ok"] is False

    def test_default_runner_without_cascade(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.gep import solidify as solidify_mod
        from evolver.gep.workflow import default_cascade_runner

        monkeypatch.setattr(solidify_mod, "get_fitness_cascade_commands", lambda: [])
        verdict = default_cascade_runner()
        assert verdict["overall_ok"] is False
        assert verdict["failed_stages"] == ["no-runnable-cascade"]


class TestAgentRoles:
    def test_awaiting_agent_metadata(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace)
        state = engine.create(
            _spec(
                {
                    "kind": "agent",
                    "role": "mutator",
                    "description": "apply the repair",
                    "instruction": "implement the selected gene",
                }
            )
        )
        engine.run(state)
        assert state.status == ST_WAITING_AGENT
        info = engine.awaiting_agent("wf1")
        assert info["waiting"] is True
        assert info["role"] == "mutator"
        assert info["instruction"] == "implement the selected gene"
        wal = json.loads(
            (temp_workspace / "workflows" / "wf1.wal.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[-1]
        )
        assert wal["role"] == "mutator"
        state = engine.complete_agent("wf1", {"ok": True})
        assert state.status == ST_DONE

    def test_awaiting_approval_metadata(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace)
        state = engine.create(
            _spec({"kind": "approval", "risk_reason": "publish genome", "description": "risky"})
        )
        engine.run(state)
        info = engine.awaiting_approval("wf1")
        assert info["waiting"] is True
        assert info["risk_reason"] == "publish genome"

    def test_awaiting_agent_when_not_waiting(self, temp_workspace: Path) -> None:
        engine = _engine(temp_workspace)
        state = engine.create(_spec({"kind": "script", "name": "noop"}))
        engine.run(state)
        assert engine.awaiting_agent("wf1") == {"waiting": False, "status": ST_DONE}


class TestSwarmWorkflowSurface:
    def test_template_full_loop(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.swarm import swarm_workflow_act, swarm_workflow_run, swarm_workflow_status

        monkeypatch.setattr("evolver.gep.workflow.default_cascade_runner", lambda: _gate(True))
        run = swarm_workflow_run(template="innovate", workflow_id="swf1")
        assert run["ok"] is True
        assert run["status"] == "waiting_agent"
        assert run["awaiting_agent"]["role"] == "innovator"

        stepped = swarm_workflow_act("swf1", "complete", result={"ok": True, "files": 2})
        assert stepped["ok"] is True
        assert stepped["status"] == "waiting_approval"
        assert "keep the innovation" in stepped["awaiting_approval"]["risk_reason"]

        final = swarm_workflow_act("swf1", "approve")
        assert final["ok"] is True
        assert final["status"] == "done"

        status = swarm_workflow_status("swf1")
        assert status["ok"] is True
        assert status["status"] == "done"

    def test_template_reject_path(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.swarm import swarm_workflow_act, swarm_workflow_run

        monkeypatch.setattr("evolver.gep.workflow.default_cascade_runner", lambda: _gate(False))
        swarm_workflow_run(template="innovate", workflow_id="swf2")
        swarm_workflow_act("swf2", "complete", result={"ok": True})
        # gate on_fail=skip in the template → approval still reached despite failing cascade
        stepped = swarm_workflow_act("swf2", "approve")
        assert stepped["status"] == "done"

    def test_bad_invocations(self, temp_workspace: Path) -> None:
        from evolver.swarm import swarm_workflow_act, swarm_workflow_run, swarm_workflow_status

        assert swarm_workflow_run()["ok"] is False  # neither file nor template
        assert swarm_workflow_run(file="a", template="b")["ok"] is False  # both
        assert swarm_workflow_run(template="nope")["ok"] is False
        assert swarm_workflow_status("missing-id")["ok"] is False
        assert swarm_workflow_act("missing-id", "approve")["ok"] is False

    def test_yaml_file_source(self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from evolver.gep.workflow import dump_spec_yaml
        from evolver.swarm import swarm_workflow_run

        monkeypatch.setattr("evolver.gep.workflow.default_cascade_runner", lambda: _gate(True))
        spec_path = dump_spec_yaml(
            {
                "id": "yf1",
                "steps": [
                    {"kind": "agent", "role": "reviewer", "instruction": "review the diff"},
                    {"kind": "gate"},
                ],
            },
            temp_workspace / "custom.yaml",
        )
        run = swarm_workflow_run(file=str(spec_path))
        assert run["ok"] is True
        assert run["awaiting_agent"]["role"] == "reviewer"


class TestWorkflowCli:
    def test_run_template_awaiting_complete(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        import argparse

        from evolver.cli import _cmd_workflow

        monkeypatch.setattr("evolver.gep.workflow.default_cascade_runner", lambda: _gate(True))
        args = argparse.Namespace(
            workflow_action="run", spec_file=None, template="innovate", id="cli1"
        )
        assert _cmd_workflow(args) == 1  # waiting_agent ≠ done
        out = capsys.readouterr().out
        assert "innovator" in out

        args = argparse.Namespace(workflow_action="complete", id="cli1", result=None, fail=False)
        assert _cmd_workflow(args) == 0
        args = argparse.Namespace(workflow_action="approve", id="cli1", note=None)
        assert _cmd_workflow(args) == 0

        args = argparse.Namespace(workflow_action="awaiting", id="cli1")
        assert _cmd_workflow(args) == 0
        assert "nothing awaited" in capsys.readouterr().out

    def test_templates_listing(self, capsys: pytest.CaptureFixture, temp_workspace: Path) -> None:
        import argparse

        from evolver.cli import _cmd_workflow

        args = argparse.Namespace(workflow_action="templates")
        assert _cmd_workflow(args) == 0
        out = capsys.readouterr().out
        assert "repair" in out
        assert "innovate" in out
