"""HOTL supervision — human-on-the-loop overlay (v1.101.0).

State machine (running/paused), veto patterns, steering directives (pending-
signal injection), and the degraded-streak tripwire. Counterpart to the HITL
gate (tests/gep/test_hitl.py): HOTL decides whether the loop runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep.supervision import (
    add_directive,
    add_veto,
    auto_pause_check,
    check_veto,
    get_supervision,
    is_paused,
    remove_veto,
    set_state,
    supervision_journal_path,
    supervision_summary,
)


class TestStateMachine:
    def test_defaults_to_running(self, temp_workspace: Path) -> None:
        assert get_supervision().state == "running"
        assert is_paused() is False

    def test_pause_resume_journaled(self, temp_workspace: Path) -> None:
        paused = set_state(True, by="human", reason="check something")
        assert paused["changed"] is True and paused["state"] == "paused"
        assert is_paused() is True
        # Idempotent flip.
        assert set_state(True, by="human")["changed"] is False

        resumed = set_state(False, by="human")
        assert resumed["changed"] is True and resumed["state"] == "running"
        journal = supervision_journal_path().read_text(encoding="utf-8")
        assert '"event": "paused"' in journal and '"event": "resumed"' in journal

    def test_summary_shape(self, temp_workspace: Path) -> None:
        summary = supervision_summary()
        assert summary["state"] == "running"
        assert summary["directives"] == [] and summary["vetoes"] == []


class TestDirectives:
    def test_directive_injects_pending_signal(self, temp_workspace: Path) -> None:
        from evolver.gep.asset_store import consume_pending_signals

        result = add_directive("优先稳定测试，暂停激进重构", by="human")
        assert result["ok"] is True
        pending = consume_pending_signals()
        assert any(s.startswith("supervision:directive:") and "优先稳定测试" in s for s in pending)
        assert supervision_summary()["directives"][0]["by"] == "human"

    def test_empty_directive_rejected(self, temp_workspace: Path) -> None:
        assert add_directive("   ")["ok"] is False


class TestVetoes:
    def test_substring_match_casefolded(self, temp_workspace: Path) -> None:
        assert add_veto("Gene_Big_Refactor")["ok"] is True
        hit = check_veto("plan: apply gene_big_refactor now")
        assert hit is not None and hit["pattern"] == "Gene_Big_Refactor"
        assert check_veto("unrelated subject") is None

    def test_unveto(self, temp_workspace: Path) -> None:
        created = add_veto("gene_x")
        removed = remove_veto(created["veto_id"])
        assert removed["ok"] is True
        assert remove_veto(created["veto_id"])["ok"] is False
        assert check_veto("gene_x again") is None

    def test_empty_pattern_rejected(self, temp_workspace: Path) -> None:
        assert add_veto("  ")["ok"] is False


class TestTripwire:
    def test_streak_auto_pauses(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from evolver.gep.feedback import EvaluationFeedback, record_feedback

        monkeypatch.setattr("evolver.config.SUPERVISION_AUTO_PAUSE_STREAK", 3)
        for _ in range(2):
            record_feedback(EvaluationFeedback(primary_score=0.9))
        assert auto_pause_check()["streak"] == 0

        for _ in range(3):
            record_feedback(EvaluationFeedback(primary_score=0.1))
        result = auto_pause_check()
        assert result["streak"] == 3
        assert is_paused() is True
        assert get_supervision().paused_by == "auto:degraded_streak"

    def test_disabled_when_zero(
        self, temp_workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("evolver.config.SUPERVISION_AUTO_PAUSE_STREAK", 0)
        assert auto_pause_check() == {"checked": False, "streak": 0}
