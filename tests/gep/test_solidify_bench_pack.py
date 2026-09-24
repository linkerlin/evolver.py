"""Tests for the frozen bench-pack gate inside solidify (round-79).

Charter 外部适应度 step 2: the pack is an additional acceptance condition —
a drop rejects (rollback + ``bench_pack_rejected`` failure event), flat or
up passes and rides onto the event, an absent pack (or gate trouble)
degrades to inactive with solidify byte-identical. The T0 acceptance hook
is mocked to ``None`` here (its own contract lives in
``test_solidify_acceptance_hook.py``); the pack gate is exercised through
its ``gate_verdict`` seam.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from evolver.bench import frozen_gate as gate_mod
from evolver.gep import git_ops
from evolver.gep import solidify as solidify_mod
from evolver.gep.acceptance import solidify_hook as hook_mod
from evolver.gep.asset_store import read_all_events
from evolver.gep.solidify import solidify, write_state_for_solidify


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_git_repo(ws: Path) -> None:
    _git(ws, "init")
    _git(ws, "config", "user.email", "test@test.com")
    _git(ws, "config", "user.name", "Test")
    (ws / "README.md").write_text("init\n", encoding="utf-8")
    _git(ws, "add", "-A")
    _git(ws, "-c", "commit.gpgsign=false", "commit", "-m", "init")


def _last_run() -> dict[str, Any]:
    return {
        "run_id": "run_test_bench_pack",
        "selected_gene_id": "gene_test_bench_pack",
        "signals": ["test"],
        "mutation": {
            "type": "Mutation",
            "id": "mut_test_bench_pack",
            "category": "repair",
            "validation": [],
        },
    }


@pytest.fixture
def git_ws(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(temp_workspace))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    gep = temp_workspace / ".evolver" / "gep"
    gep.mkdir(parents=True, exist_ok=True)
    (gep / "events.jsonl").write_text("", encoding="utf-8")
    evo = temp_workspace / "memory" / "evolution"
    evo.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("GEP_ASSETS_DIR", str(gep))
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))
    monkeypatch.setenv("EVOLVER_HOME", str(temp_workspace / ".evomap-home"))
    monkeypatch.setattr(
        solidify_mod,
        "rollback_tracked",
        lambda **kw: git_ops.rollback_tracked(**{**kw, "cwd": temp_workspace}),
    )
    # T0 acceptance hook inert here — the pack gate is under test.
    monkeypatch.setattr(hook_mod, "gate_for_solidify", lambda _r, _c: None)
    _init_git_repo(temp_workspace)
    return temp_workspace


def _uncommitted_change(ws: Path) -> Path:
    p = ws / "patched.txt"
    p.write_text("patched\n", encoding="utf-8")
    _git(ws, "add", "patched.txt")
    _git(ws, "-c", "commit.gpgsign=false", "commit", "-m", "patch applied")
    p.write_text("patched v2\n", encoding="utf-8")
    return p


def _verdict(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    verdict: dict[str, Any] = {
        "armed": True,
        "pack": "/frozen/charter-pack.tasks.json",
        "digest": "abc123",
        "split": "val",
        "score": 1.0,
        "baseline": 1.0,
        "verdict": "pass",
        "per_task": [{"id": "t1", "status": "graded", "score": 1.0}],
    }
    verdict.update(overrides or {})
    return verdict


class TestInactiveGate:
    def test_absent_pack_solidify_unchanged(self, git_ws: Path) -> None:
        """Fresh env: no frozen pack → gate inactive, no event field, no
        rejection — solidify behaves exactly as before the charter."""
        _ = git_ws
        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["ok"] is True
        assert "bench_pack" not in result
        ev = read_all_events()[-1]
        assert "bench_pack" not in ev

    def test_gate_error_degrades_to_inactive(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ = git_ws
        monkeypatch.setattr(gate_mod, "gate_verdict", lambda: (_ for _ in ()).throw(OSError("x")))
        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["ok"] is True
        assert "bench_pack" not in read_all_events()[-1]


class TestGatePass:
    def test_pass_rides_onto_event_and_return(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ = git_ws
        monkeypatch.setattr(gate_mod, "gate_verdict", _verdict)
        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["ok"] is True
        assert result["bench_pack"] == {"score": 1.0, "baseline": 1.0, "verdict": "pass"}
        ev = read_all_events()[-1]
        assert ev["bench_pack"]["verdict"] == "pass"
        assert ev["bench_pack"]["digest"] == "abc123"
        assert ev["bench_pack"]["per_task"] == [{"id": "t1", "status": "graded", "score": 1.0}]

    def test_accept_return_carries_cascade_score_slot(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Charter: the host's primary_score sources from the cascade — the
        success return must expose the measured score slot (None when
        unvalidated, never fabricated)."""
        _ = git_ws
        monkeypatch.setattr(gate_mod, "gate_verdict", _verdict)
        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert "score" in result
        assert result["score"] is None  # skip_validation: unvalidated claims nothing


class TestGateReject:
    def test_drop_rejects_with_failure_event(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ = git_ws
        monkeypatch.setattr(
            gate_mod,
            "gate_verdict",
            lambda: _verdict({"score": 0.6, "baseline": 1.0, "verdict": "reject"}),
        )
        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["ok"] is False
        assert result["error"] == "bench_pack_rejected"
        assert result["details"]["bench_pack"]["score"] == 0.6
        # Loop-continuation semantics: a fitness floor is not a crash.
        assert result["failure_mode"] == {
            "mode": "soft",
            "reasonClass": "bench_pack",
            "retryable": True,
        }
        assert result["next_action"] == "swarm_tick"

    def test_drop_rolls_back_working_tree(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            gate_mod,
            "gate_verdict",
            lambda: _verdict({"score": 0.6, "baseline": 1.0, "verdict": "reject"}),
        )
        patched = _uncommitted_change(git_ws)
        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["ok"] is False
        assert patched.read_text(encoding="utf-8") == "patched\n"

    def test_failure_event_carries_pack_evidence(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ = git_ws
        monkeypatch.setattr(
            gate_mod,
            "gate_verdict",
            lambda: _verdict({"score": 0.6, "baseline": 1.0, "verdict": "reject"}),
        )
        write_state_for_solidify(_last_run())
        solidify(skip_validation=True)
        events = read_all_events()
        assert len(events) == 1, "rejected mutation must not land a success event"
        ev = events[0]
        assert ev["outcome"]["error"] == "bench_pack_rejected"
        assert ev["outcome"]["score"] == 0.6
        assert ev["bench_pack"]["verdict"] == "reject"
