"""Sprint 22.5 + 22.6: acceptance shadow mode / gray-scale report + GEPA
lineage lessons (parent_event_id, prompt ancestry block).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from evolver.gep import solidify as solidify_mod
from evolver.gep.acceptance.report import summarize_acceptance
from evolver.gep.acceptance.schemas import AcceptanceResult
from evolver.gep.asset_store import read_all_events
from evolver.gep.solidify import solidify, write_state_for_solidify


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


def _last_run() -> dict[str, Any]:
    return {
        "run_id": "run_shadow",
        "selected_gene_id": "gene_shadow",
        "signals": ["log_error"],
        "mutation": {
            "type": "Mutation",
            "id": "mut_shadow",
            "category": "repair",
            "validation": [],
        },
    }


def _rejected() -> AcceptanceResult:
    return AcceptanceResult(accepted=False, reason="T0_frozen_regressed")


def _accepted() -> AcceptanceResult:
    return AcceptanceResult(accepted=True, reason="t0_only_no_regression")


class TestShadowMode:
    def test_shadow_reject_still_solidifies(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_ACCEPTANCE_GATE", "true")
        # ACCEPTANCE_SHADOW is an import-time config Final — patch the module
        # attribute (same lookup the code uses).
        monkeypatch.setattr(solidify_mod, "ACCEPTANCE_SHADOW", True)
        monkeypatch.setattr(
            "evolver.gep.acceptance.solidify_hook.gate_for_solidify",
            lambda lr, cwd: _rejected(),
        )
        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["ok"] is True  # shadow: never enforce
        events = read_all_events()
        acc = events[-1]["acceptance_result"]
        assert acc["shadow"] is True
        assert acc["would_accept"] is False
        assert acc["reason"] == "T0_frozen_regressed"

    def test_enforcing_reject_still_rejects(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_ACCEPTANCE_GATE", "true")
        monkeypatch.setattr(solidify_mod, "ACCEPTANCE_SHADOW", False)
        monkeypatch.setattr(
            "evolver.gep.acceptance.solidify_hook.gate_for_solidify",
            lambda lr, cwd: _rejected(),
        )
        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["ok"] is False
        assert result["error"] == "acceptance_gate_rejected"

    def test_shadow_accept_has_no_shadow_marker(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_ACCEPTANCE_GATE", "true")
        monkeypatch.setattr(solidify_mod, "ACCEPTANCE_SHADOW", True)
        monkeypatch.setattr(
            "evolver.gep.acceptance.solidify_hook.gate_for_solidify",
            lambda lr, cwd: _accepted(),
        )
        write_state_for_solidify(_last_run())
        result = solidify(skip_validation=True)
        assert result["ok"] is True
        acc = read_all_events()[-1]["acceptance_result"]
        assert "shadow" not in acc


class TestSummarizeAcceptance:
    def test_empty(self) -> None:
        assert summarize_acceptance([]) == {
            "gated_runs": 0,
            "shadow_rejected": 0,
            "interception_rate": 0.0,
            "validation_disagreements": 0,
            "false_kill_risk": None,
            "window": {"first": None, "last": None},
        }

    def test_metrics(self) -> None:
        events = [
            {"acceptance_result": {"shadow": True, "would_accept": False}},
            {
                "acceptance_result": {"shadow": True, "would_accept": False},
                "validation_report": {"overall_ok": True},
            },
            {"acceptance_result": {"reason": "t0_only_no_regression"}},
            {"outcome": {}},
        ]
        m = summarize_acceptance(events)
        assert m["gated_runs"] == 3
        assert m["shadow_rejected"] == 2
        assert m["interception_rate"] == round(2 / 3, 4)
        assert m["validation_disagreements"] == 1
        assert m["false_kill_risk"] == 0.5


class TestLineageLessons:
    def test_builder_collects_failures_newest_first(self) -> None:
        from evolver.evolve.pipeline.dispatch import _build_lineage_lessons

        events = [
            {
                "gene_id": "g1",
                "outcome": {"status": "success", "score": 1.0},
                "mutation": {"category": "repair"},
            },
            {
                "gene_id": "g1",
                "outcome": {"status": "failed", "error": "validation_failed"},
                "mutation": {"category": "repair"},
                "blast_radius": {"files": 2, "lines": 30},
                "signals": ["log_error"],
            },
            {
                "gene_id": "g2",
                "outcome": {"status": "failed", "error": "other_gene"},
                "mutation": {"category": "optimize"},
            },
            {
                "gene_id": "g1",
                "outcome": {"status": "failed", "error": "T0_frozen_regressed"},
                "mutation": {"category": "innovate"},
                "blast_radius": {"files": 1, "lines": 5},
                "signals": ["capability_gap"],
            },
        ]
        block = _build_lineage_lessons("g1", events)
        assert "Lineage Lessons" in block
        assert "T0_frozen_regressed" in block  # newest first
        assert "other_gene" not in block  # other genes excluded
        assert "innovate" in block and "repair" in block

    def test_builder_no_failures_returns_empty(self) -> None:
        from evolver.evolve.pipeline.dispatch import _build_lineage_lessons

        assert _build_lineage_lessons("g1", [{"gene_id": "g1", "outcome": {}}]) == ""
        assert _build_lineage_lessons("", [{"gene_id": "g1"}]) == ""

    def test_event_carries_parent_event_id_when_enabled(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("EVOLVER_FF_ENABLE_LINEAGE_LESSONS", "true")
        write_state_for_solidify(_last_run())
        solidify(skip_validation=True)
        first = read_all_events()[-1]
        write_state_for_solidify(_last_run())
        solidify(skip_validation=True)
        second = read_all_events()[-1]
        assert "parent_event_id" not in first  # no predecessor
        assert second["parent_event_id"] == first["id"]

    def test_event_has_no_parent_when_disabled(
        self, git_ws: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("EVOLVER_FF_ENABLE_LINEAGE_LESSONS", raising=False)
        write_state_for_solidify(_last_run())
        solidify(skip_validation=True)
        assert "parent_event_id" not in read_all_events()[-1]
