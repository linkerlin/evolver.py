"""Sprint 22.2 fitness cascade: engine-owned validation + graded score.

Covers the methodology-audit gap "fitness = didn't crash" (演进方案.md §13.2-#4).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from evolver.gep import solidify


def _fake_proc(rc: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)


class TestNormalizeValidationCommand:
    def test_str(self) -> None:
        argv, display, timeout = solidify._normalize_validation_command("pytest -q")
        assert argv == ["pytest -q"]
        assert display == "pytest -q"
        assert timeout is None

    def test_list(self) -> None:
        argv, _display, timeout = solidify._normalize_validation_command(
            ["pytest", "-m", "not slow"]
        )
        assert argv == ["pytest", "-m", "not slow"]
        assert timeout is None

    def test_dict_spec_timeout(self) -> None:
        argv, _display, timeout = solidify._normalize_validation_command(
            {"command": ["pytest"], "timeout_ms": 600_000}
        )
        assert argv == ["pytest"]
        assert timeout == 600_000


class TestRunValidationsCascade:
    def test_short_circuits_on_first_failure(self, monkeypatch: Any, tmp_path: Path) -> None:
        calls: list[Any] = []

        def fake_run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
            calls.append(argv)
            return _fake_proc(rc=1)

        monkeypatch.setattr(solidify.subprocess, "run", fake_run)
        result = solidify._run_validations(
            [{"command": ["ruff", "check"]}, {"command": ["mypy"]}, {"command": ["pytest"]}],
            tmp_path,
            cascade=True,
        )
        assert result["ok"] is False
        assert len(calls) == 1  # mypy/pytest never reached
        assert len(result["results"]) == 1

    def test_non_cascade_runs_all(self, monkeypatch: Any, tmp_path: Path) -> None:
        calls: list[Any] = []

        def fake_run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
            calls.append(argv)
            return _fake_proc(rc=1)

        monkeypatch.setattr(solidify.subprocess, "run", fake_run)
        result = solidify._run_validations(
            [{"command": ["ruff"]}, {"command": ["mypy"]}], tmp_path, cascade=False
        )
        assert len(calls) == 2
        assert result["ok"] is False

    def test_dict_spec_timeout_used(self, monkeypatch: Any, tmp_path: Path) -> None:
        seen: dict[str, Any] = {}

        def fake_run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
            seen.update(kwargs)
            return _fake_proc(rc=0)

        monkeypatch.setattr(solidify.subprocess, "run", fake_run)
        solidify._run_validations([{"command": ["pytest"], "timeout_ms": 600_000}], tmp_path)
        assert seen["timeout"] == 600.0


class TestCascadeScore:
    def test_all_ok(self) -> None:
        results = [{"ok": True}, {"ok": True}, {"ok": True}]
        assert solidify._cascade_score(results) == 1.0

    def test_first_stage_fail_zero(self) -> None:
        results = [{"ok": False, "stdout": "ruff errors", "stderr": ""}]
        assert solidify._cascade_score(results) == 0.0

    def test_pytest_partial_credit(self) -> None:
        results = [
            {"ok": True},
            {"ok": True},
            {"ok": False, "stdout": "12 failed, 2900 passed in 60s", "stderr": ""},
        ]
        rate = 2900 / 2912
        assert solidify._cascade_score(results) == round((2 + rate) / 3, 4)

    def test_pytest_errors_counted(self) -> None:
        results = [{"ok": False, "stdout": "12 passed, 3 errors", "stderr": ""}]
        rate = 12 / 15
        assert solidify._cascade_score(results) == round(rate / 1, 4)


class TestParsePytestRate:
    def test_mixed(self) -> None:
        assert solidify._parse_pytest_rate("2900 passed, 12 failed in 60s") == 2900 / 2912

    def test_all_passed(self) -> None:
        assert solidify._parse_pytest_rate("3012 passed, 2 warnings in 375s") == 1.0

    def test_no_passed_line(self) -> None:
        assert solidify._parse_pytest_rate("collection error") is None

    def test_empty(self) -> None:
        assert solidify._parse_pytest_rate("") is None


class TestFitnessCascadeCommands:
    def test_engine_owned_three_stages(self) -> None:
        cmds = solidify.get_fitness_cascade_commands()
        assert len(cmds) == 3
        assert cmds[0]["command"][0] == "ruff"
        assert cmds[1]["command"][0] == "mypy"
        assert cmds[2]["command"][0] == "pytest"
        assert cmds[2]["timeout_ms"] >= 600_000

    def test_deep_copy(self) -> None:
        a = solidify.get_fitness_cascade_commands()
        a[0]["command"].append("mutated")
        assert solidify.get_fitness_cascade_commands()[0]["command"][-1] != "mutated"


class TestCascadeFailurePath:
    def test_failed_event_appended_with_score(self, monkeypatch: Any, tmp_path: Path) -> None:
        order: list[str] = []
        appended: dict[str, Any] = {}
        recorded: dict[str, Any] = {}

        def fake_blast() -> dict[str, Any]:
            order.append("blast")
            return {"files": 2, "lines": 10}

        monkeypatch.setattr(solidify, "_compute_blast_radius", fake_blast)
        monkeypatch.setattr(solidify, "rollback_tracked", lambda **kw: order.append("rollback"))
        monkeypatch.setattr(
            solidify, "rollback_new_untracked_files", lambda *a, **kw: order.append("rollback2")
        )
        monkeypatch.setattr(solidify, "git_list_untracked_files", lambda cwd: [])
        monkeypatch.setattr(solidify, "append_event_jsonl", appended.update)
        monkeypatch.setattr(
            solidify,
            "record_solidify_failure",
            lambda last_run, *, error, score=None: recorded.update(
                {"error": error, "score": score}
            ),
        )

        last_run = {
            "run_id": "run-1",
            "selected_gene_id": "gene-1",
            "signals": ["log_error"],
        }
        mutation = {"type": "Mutation", "id": "mut-1", "category": "repair"}
        result = solidify._handle_cascade_validation_failure(
            last_run=last_run,
            mutation=mutation,
            cwd=tmp_path,
            validation_result={
                "ok": False,
                "results": [{"ok": False, "stdout": "2 failed, 98 passed", "stderr": ""}],
                "started_at": 0.0,
                "finished_at": 1.0,
            },
            validation_report=None,
        )
        # blast captured before rollback
        assert order == ["blast", "rollback", "rollback2"]
        # graded score on the failed event
        assert appended["outcome"]["status"] == "failed"
        assert appended["outcome"]["score"] == 0.98
        assert appended["gene_id"] == "gene-1"
        assert result["ok"] is False
        assert result["details"]["score"] == 0.98
        # memory-graph failure carries the partial score
        assert recorded == {"error": "validation_failed", "score": 0.98}


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def git_ws(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(temp_workspace))
    gep = temp_workspace / ".evolver" / "gep"
    gep.mkdir(parents=True, exist_ok=True)
    (gep / "events.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setenv("GEP_ASSETS_DIR", str(gep))
    _git(temp_workspace, "init")
    _git(temp_workspace, "config", "user.email", "test@test.com")
    _git(temp_workspace, "config", "user.name", "Test")
    (temp_workspace / "README.md").write_text("init\n", encoding="utf-8")
    _git(temp_workspace, "add", "-A")
    _git(temp_workspace, "-c", "commit.gpgsign=false", "commit", "-m", "init")
    return temp_workspace


class TestSolidifyFlagIntegration:
    def _prepare(self, ws: Path) -> None:
        from evolver.gep.solidify import write_state_for_solidify

        write_state_for_solidify(
            {
                "run_id": "run-fit",
                "selected_gene_id": "gene-fit",
                "signals": ["log_error"],
                "mutation": {
                    "type": "Mutation",
                    "id": "mut-fit",
                    "category": "repair",
                    "validation": ["totally-not-allowed -c rm -rf"],
                },
            }
        )

    def test_flag_on_ignores_mutation_validation(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_FITNESS_CASCADE", "true")
        self._prepare(git_ws)
        captured: dict[str, Any] = {}

        def fake_run_validations(
            commands: list[Any], cwd: Path, *, cascade: bool = False
        ) -> dict[str, Any]:
            captured.update({"commands": commands, "cascade": cascade})
            return {"ok": True, "results": [], "started_at": 0.0, "finished_at": 1.0}

        monkeypatch.setattr(solidify, "_run_validations", fake_run_validations)
        monkeypatch.setattr(solidify, "post_solidify_hooks", lambda *a, **k: {})
        monkeypatch.setattr(solidify, "record_narrative_and_reflection", lambda *a, **k: None)
        result = solidify.solidify()
        assert result["ok"] is True
        # engine-owned cascade, not the (untrusted) mutation.validation
        assert captured["commands"] == solidify.get_fitness_cascade_commands()
        assert captured["cascade"] is True

    def test_flag_off_keeps_mutation_validation(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._prepare(git_ws)
        captured: dict[str, Any] = {}

        def fake_run_validations(
            commands: list[Any], cwd: Path, *, cascade: bool = False
        ) -> dict[str, Any]:
            captured.update({"commands": commands, "cascade": cascade})
            return {"ok": True, "results": [], "started_at": 0.0, "finished_at": 1.0}

        monkeypatch.setattr(solidify, "_run_validations", fake_run_validations)
        monkeypatch.setattr(solidify, "post_solidify_hooks", lambda *a, **k: {})
        monkeypatch.setattr(solidify, "record_narrative_and_reflection", lambda *a, **k: None)
        result = solidify.solidify()
        assert result["ok"] is True
        assert captured["commands"] == ["totally-not-allowed -c rm -rf"]
        assert captured["cascade"] is False
