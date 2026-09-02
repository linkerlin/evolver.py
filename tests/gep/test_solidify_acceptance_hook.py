"""Tests for the acceptance-gate hook inside solidify (Sprint A1.5).

Verifies the integration seam: flag-off no-op, gate-reject → rollback +
``acceptance_gate_rejected``, gate-accept → event carries ``acceptance_result``.

The gate itself (``evolver.gep.acceptance.*``) is exercised in
``tests/gep/acceptance/``; here :func:`gate_for_solidify` is mocked so these
tests are fast and deterministic. The mock faithfully replicates the real
hook's flag check (returns ``None`` when ``enable_acceptance_gate`` is off).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from evolver.gep import git_ops
from evolver.gep import solidify as solidify_mod
from evolver.gep.acceptance import solidify_hook as hook_mod
from evolver.gep.acceptance.schemas import AcceptanceResult
from evolver.gep.asset_store import read_all_events
from evolver.gep.feature_flags import is_enabled
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


def _last_run(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "run_id": "run_test_acceptance_hook",
        "selected_gene_id": "gene_test_acceptance_hook",
        "signals": ["test"],
        "mutation": {
            "type": "Mutation",
            "id": "mut_test_acceptance_hook",
            "category": "repair",
            "validation": [],
        },
    }
    base.update(overrides)
    return base


@pytest.fixture
def git_ws(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(temp_workspace))
    gep = temp_workspace / ".evolver" / "gep"
    gep.mkdir(parents=True, exist_ok=True)
    (gep / "events.jsonl").write_text("", encoding="utf-8")
    evo = temp_workspace / "memory" / "evolution"
    evo.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("GEP_ASSETS_DIR", str(gep))
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))
    # Patch solidify's imported name so any legacy no-cwd rollback still
    # targets THIS workspace. (chdir is avoided: on Windows the temp
    # workspace can't be removed while it is the process cwd.)
    monkeypatch.setattr(
        solidify_mod,
        "rollback_tracked",
        lambda **kw: git_ops.rollback_tracked(**{**kw, "cwd": temp_workspace}),
    )
    _init_git_repo(temp_workspace)
    return temp_workspace


def _uncommitted_change(ws: Path) -> Path:
    """Create a tracked file, commit it, then modify it (uncommitted change)."""
    p = ws / "patched.txt"
    p.write_text("patched\n", encoding="utf-8")
    _git(ws, "add", "patched.txt")
    _git(ws, "-c", "commit.gpgsign=false", "commit", "-m", "patch applied")
    # Now modify the working tree (uncommitted change to be rolled back).
    p.write_text("patched v2\n", encoding="utf-8")
    return p


def _patch_gate(
    monkeypatch: pytest.MonkeyPatch,
    result: AcceptanceResult,
    *,
    called: list[bool] | None = None,
) -> None:
    """Monkeypatch the lazy-imported gate_for_solidify, replicating the real
    flag check (returns None when the gate flag is off)."""

    def fake_gate(_last_run: dict[str, Any], _cwd: Any) -> AcceptanceResult | None:
        if called is not None:
            called.append(True)
        if not is_enabled("enable_acceptance_gate"):
            return None
        return result

    monkeypatch.setattr(hook_mod, "gate_for_solidify", fake_gate)


def _accepted() -> AcceptanceResult:
    return AcceptanceResult(accepted=True, reason="t0_only_no_regression")


def _rejected() -> AcceptanceResult:
    return AcceptanceResult(accepted=False, reason="T0_frozen_regressed")


def _read_events() -> list[dict[str, Any]]:
    return read_all_events()


class TestFlagOff:
    def test_gate_flag_off_means_no_acceptance_result(
        self,
        git_ws: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _ = git_ws  # fixture side-effects (env + git repo) only
        monkeypatch.setenv("EVOLVER_FF_ENABLE_ACCEPTANCE_GATE", "0")
        called: list[bool] = []
        _patch_gate(monkeypatch, _accepted(), called=called)
        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["ok"] is True
        # hook invoked but flag-gated to None → event carries no acceptance
        assert called == [True]
        events = _read_events()
        ev = events[-1]
        assert "acceptance_result" not in ev


class TestGateReject:
    """Enforcement path — shadow mode (S26 default) must be off here."""

    def test_reject_returns_error(self, git_ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _ = git_ws
        monkeypatch.setenv("EVOLVER_FF_ENABLE_ACCEPTANCE_GATE", "1")
        monkeypatch.setattr(solidify_mod, "ACCEPTANCE_SHADOW", False)
        _patch_gate(monkeypatch, _rejected())
        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["ok"] is False
        assert result["error"] == "acceptance_gate_rejected"
        assert result["details"]["acceptance"]["accepted"] is False

    def test_reject_rolls_back_working_tree(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_ACCEPTANCE_GATE", "1")
        monkeypatch.setattr(solidify_mod, "ACCEPTANCE_SHADOW", False)
        _patch_gate(monkeypatch, _rejected())
        patched = _uncommitted_change(git_ws)
        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["ok"] is False
        # rollback_tracked (stash) restored the committed version
        assert patched.read_text(encoding="utf-8") == "patched\n"


class TestGateAccept:
    def test_accept_attaches_result_to_event(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ = git_ws
        monkeypatch.setenv("EVOLVER_FF_ENABLE_ACCEPTANCE_GATE", "1")
        _patch_gate(monkeypatch, _accepted())
        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["ok"] is True
        events = _read_events()
        ev = events[-1]
        assert ev["acceptance_result"]["accepted"] is True
        assert ev["acceptance_result"]["reason"] == "t0_only_no_regression"
