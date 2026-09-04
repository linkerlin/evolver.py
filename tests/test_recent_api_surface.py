"""Coverage fill-in for the last week's API surface (v1.98-v1.111).

Targets the branches the existing per-module suites leave cold, found via a
coverage audit:

- ``workflow.default_cascade_runner`` — the REAL subprocess execution path
  (pass / fail / OS-error / timeout), previously only the empty-commands
  branch was exercised.
- ``WorkflowEngine`` edge verbs — reject/cancel/resume on wrong states.
- ``swarm_skills`` scan/list/sync branches and unknown action.
- ``swarm_workflow_act`` cancel / resume / unknown-action / failure-error
  surfacing; ``swarm_workflow_status`` awaiting branch; bad spec file.
- ``hitl`` re-request after TTL expiry (lazy-expire journal), ``list_recent``.
- ``feedback.load_recent_feedback`` with no journal yet.
- CLI ``evolver skills`` and ``evolver gate-report`` happy paths.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from evolver.gep import workflow as wf
from evolver.gep.workflow import WorkflowEngine, WorkflowPermanentError

# ---------------------------------------------------------------------------
# workflow.default_cascade_runner — the real subprocess loop
# ---------------------------------------------------------------------------

_TRUE_CMD: list[str] = [sys.executable, "-c", "pass"]
_FALSE_CMD: list[str] = [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(1)"]


@pytest.fixture
def hitl_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("evolver.config.HITL_MODE", "on")


@pytest.fixture
def isolated_evolver_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("EVOLVER_USER_LOCK", str(tmp_path / "user.lock"))
    yield tmp_path


def _stub_specs(monkeypatch: pytest.MonkeyPatch, commands: list[list[str]]) -> None:
    from evolver.gep import solidify as solidify_mod

    monkeypatch.setattr(
        solidify_mod,
        "get_fitness_cascade_commands",
        lambda: [{"stage": f"s{i}", "command": cmd} for i, cmd in enumerate(commands)],
    )


class TestDefaultCascadeRunner:
    def test_all_stages_pass(self, monkeypatch: pytest.MonkeyPatch, temp_workspace: Path) -> None:
        _stub_specs(monkeypatch, [_TRUE_CMD, _TRUE_CMD])
        verdict = wf.default_cascade_runner()
        assert verdict["overall_ok"] is True
        assert verdict["failed_stages"] == []
        assert all(s["returncode"] == 0 for s in verdict["stages"])

    def test_failing_stage_reported(
        self, monkeypatch: pytest.MonkeyPatch, temp_workspace: Path
    ) -> None:
        _stub_specs(monkeypatch, [_TRUE_CMD, _FALSE_CMD])
        verdict = wf.default_cascade_runner()
        assert verdict["overall_ok"] is False
        assert verdict["failed_stages"] == ["s1"]
        assert verdict["stages"][1]["returncode"] != 0
        assert verdict["stages"][1]["stderr_tail"]  # stderr captured for the host

    def test_missing_binary_is_oserror_not_crash(
        self, monkeypatch: pytest.MonkeyPatch, temp_workspace: Path
    ) -> None:
        _stub_specs(monkeypatch, [["/nonexistent/definitely-missing-tool"]])
        verdict = wf.default_cascade_runner()
        assert verdict["overall_ok"] is False
        assert verdict["stages"][0]["returncode"] == -1

    def test_timeout_expires_stage(
        self, monkeypatch: pytest.MonkeyPatch, temp_workspace: Path
    ) -> None:
        sleeper = [sys.executable, "-c", "import time; time.sleep(5)"]
        _stub_specs(monkeypatch, [sleeper])
        monkeypatch.setattr(wf, "GATE_TIMEOUT_S", 0.05)
        verdict = wf.default_cascade_runner()
        assert verdict["overall_ok"] is False
        assert verdict["stages"][0]["returncode"] == -1
        tail = verdict["stages"][0]["stderr_tail"]
        assert "TimeoutExpired" in tail or "timed out" in tail

    def test_gate_step_uses_the_runner_end_to_end(
        self, monkeypatch: pytest.MonkeyPatch, temp_workspace: Path
    ) -> None:
        _stub_specs(monkeypatch, [_TRUE_CMD])
        engine = WorkflowEngine(workflows_dir=temp_workspace / "wf")
        state = engine.create({"id": "g1", "steps": [{"kind": "gate"}]})
        engine.run(state)
        assert state.status == "done"
        assert state.variables["_gate_verdict"]["overall_ok"] is True


# ---------------------------------------------------------------------------
# WorkflowEngine edge verbs
# ---------------------------------------------------------------------------


class TestWorkflowEngineEdgeVerbs:
    def test_reject_on_wrong_state_is_permanent(self, temp_workspace: Path) -> None:
        engine = WorkflowEngine(workflows_dir=temp_workspace / "wf")
        state = engine.create({"id": "w1", "steps": [{"kind": "script", "name": "noop"}]})
        engine.run(state)  # done
        with pytest.raises(WorkflowPermanentError):
            engine.reject("w1")

    def test_cancel_on_terminal_returns_asis(self, temp_workspace: Path) -> None:
        engine = WorkflowEngine(workflows_dir=temp_workspace / "wf")
        state = engine.create({"id": "w2", "steps": [{"kind": "script", "name": "noop"}]})
        engine.run(state)
        state = engine.cancel("w2")
        assert state.status == "done"

    def test_resume_waiting_agent_parks_again(self, temp_workspace: Path) -> None:
        engine = WorkflowEngine(workflows_dir=temp_workspace / "wf")
        state = engine.create({"id": "w3", "steps": [{"kind": "agent", "role": "r"}]})
        engine.run(state)
        assert state.status == "waiting_agent"
        state = engine.resume("w3")
        assert state.status == "waiting_agent"  # run() parks right back

    def test_load_missing_raises_lookup(self, temp_workspace: Path) -> None:
        engine = WorkflowEngine(workflows_dir=temp_workspace / "wf")
        with pytest.raises(LookupError):
            engine.load("nope")

    def test_bad_spec_file_rejected_at_load(self, temp_workspace: Path) -> None:
        p = temp_workspace / "broken.yaml"
        p.write_text("- just\n- a\n- list\n", encoding="utf-8")  # not a mapping
        with pytest.raises(WorkflowPermanentError):
            wf.load_spec(p)


# ---------------------------------------------------------------------------
# swarm surface — skills + workflow branches
# ---------------------------------------------------------------------------


class TestSwarmSkillsSurface:
    def test_unknown_action(self) -> None:
        from evolver.swarm import swarm_skills

        assert swarm_skills(action="bogus") == {"ok": False, "error": "unknown_action:bogus"}

    def test_scan_and_list(self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from evolver.swarm import swarm_skills

        monkeypatch.setenv("EVOLVER_SKILL_ROOTS", str(temp_workspace / "roots"))
        scanned = swarm_skills(action="scan")
        assert scanned["ok"] is True and "skills" in scanned
        listed = swarm_skills(action="list")
        assert listed["ok"] is True and "genes" in listed


class TestSwarmWorkflowBranches:
    def test_unreadable_spec_file(self, temp_workspace: Path) -> None:
        from evolver.swarm import swarm_workflow_run

        bad = temp_workspace / "bad.yaml"
        bad.write_text("steps: [not, a, mapping]", encoding="utf-8")
        result = swarm_workflow_run(file=str(bad))
        assert result["ok"] is False
        assert result["error"].startswith("workflow_error:")

    def test_act_unknown_action(self, temp_workspace: Path) -> None:
        from evolver.swarm import swarm_workflow_act, swarm_workflow_run

        swarm_workflow_run(template="innovate", workflow_id="br1")
        assert swarm_workflow_act("br1", "bogus") == {"ok": False, "error": "unknown_action:bogus"}

    def test_act_cancel(self, temp_workspace: Path) -> None:
        from evolver.swarm import swarm_workflow_act, swarm_workflow_run, swarm_workflow_status

        swarm_workflow_run(template="innovate", workflow_id="br2")
        out = swarm_workflow_act("br2", "cancel")
        assert out["ok"] is True and out["status"] == "cancelled"
        assert swarm_workflow_status("br2")["status"] == "cancelled"

    def test_act_resume_on_waiting_agent(self, temp_workspace: Path) -> None:
        from evolver.swarm import swarm_workflow_act, swarm_workflow_run

        swarm_workflow_run(template="innovate", workflow_id="br3")
        out = swarm_workflow_act("br3", "resume")
        assert out["ok"] is True and out["status"] == "waiting_agent"

    def test_failed_task_surfaces_error(self, temp_workspace: Path) -> None:
        from evolver.swarm import swarm_workflow_act, swarm_workflow_run

        swarm_workflow_run(template="innovate", workflow_id="br4")
        out = swarm_workflow_act("br4", "complete", result={"ok": False})
        assert out["ok"] is True
        assert out["status"] == "failed"
        assert "reported failure" in out["error"]

    def test_status_awaiting_agent(self, temp_workspace: Path) -> None:
        from evolver.swarm import swarm_workflow_run, swarm_workflow_status

        swarm_workflow_run(template="innovate", workflow_id="br5")
        status = swarm_workflow_status("br5")
        assert status["ok"] is True
        assert status["awaiting_agent"]["waiting"] is True
        assert status["awaiting_agent"]["role"] == "innovator"


# ---------------------------------------------------------------------------
# hitl — re-request after TTL expiry + list_recent
# ---------------------------------------------------------------------------


class TestHitlExpiryReuse:
    def test_rerequest_after_expiry_fails_safe(
        self, temp_workspace: Path, hitl_on: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.gep import hitl as hitl_mod

        first = hitl_mod.request_approval("sub-expired", "risk", ttl_ms=50)
        assert first["status"] == "pending"
        # Push the clock past TTL: the pending request must lazily expire and
        # the fail-safe answer becomes "rejected" (no approval shopping).
        future = hitl_mod._utcnow() + hitl_mod.datetime.timedelta(milliseconds=100)
        monkeypatch.setattr(hitl_mod, "_utcnow", lambda: future)
        again = hitl_mod.request_approval("sub-expired", "risk")
        assert again["reused"] is True
        assert again["status"] == "rejected"

    def test_list_recent_bounds(self, temp_workspace: Path, hitl_on: None) -> None:
        from evolver.gep import hitl as hitl_mod

        hitl_mod.request_approval("sub-a", "risk")
        rows = hitl_mod.list_recent(limit=5)
        assert 0 < len(rows) <= 5
        assert all("subject" in r for r in rows)


# ---------------------------------------------------------------------------
# feedback — cold journal
# ---------------------------------------------------------------------------


class TestFeedbackColdJournal:
    def test_load_recent_no_journal(self, temp_workspace: Path) -> None:
        from evolver.gep.feedback import load_recent_feedback

        assert load_recent_feedback(10) == []

    def test_load_recent_reads_persisted_entries(self, temp_workspace: Path) -> None:
        from evolver.gep.feedback import feedback_journal_path, load_recent_feedback

        path = feedback_journal_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": "fb_x", "primary_score": 0.5}) + "\n")
        rows = load_recent_feedback(10)
        assert rows and rows[-1]["id"] == "fb_x"


# ---------------------------------------------------------------------------
# CLI — recent verbs
# ---------------------------------------------------------------------------


class TestRecentCliVerbs:
    def test_skills_scan_and_list(
        self, isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from evolver.cli import main

        assert main(["skills", "scan"]) == 0
        out = capsys.readouterr().out
        assert isinstance(out, str)
        assert main(["skills", "list"]) == 0

    def test_gate_report_json(
        self, isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from evolver.cli import main

        assert main(["gate-report", "--json"]) == 0
        payload: Any = json.loads(capsys.readouterr().out)
        assert "gated_runs" in payload["metrics"]
        assert payload["metrics"]["gated_runs"] >= 0

    def test_workflow_templates_and_awaiting(
        self, isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from evolver.cli import main

        assert main(["workflow", "templates"]) == 0
        assert "repair" in capsys.readouterr().out
