"""HITL approval gate — EvoX HITLManager concept harvest (v1.100.0).

Contract: auto-approve when mode=off (journaled for audit), pending when
mode=on, fail-safe REJECT on TTL expiry, idempotent per subject (rejected /
expired subjects stay closed until the subject changes).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep.hitl import (
    hitl_journal_path,
    hitl_state_path,
    list_pending,
    request_approval,
    resolve_approval,
)


@pytest.fixture
def hitl_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("evolver.config.HITL_MODE", "on")


class TestModeOff:
    def test_auto_approve_with_audit_trail(self, temp_workspace: Path) -> None:
        result = request_approval(subject="solidify_skip_validation:run_1", risk_reason="demo risk")
        assert result["status"] == "approved"
        assert result["reused"] is False

        journal = hitl_journal_path().read_text(encoding="utf-8")
        assert "auto_approved" in journal
        assert "auto:hitl-off" in hitl_state_path().read_text(encoding="utf-8")


class TestModeOn:
    def test_pending_then_approve(self, temp_workspace: Path, hitl_on: None) -> None:
        first = request_approval(subject="s1", risk_reason="r")
        assert first["status"] == "pending"
        assert list_pending() and list_pending()[0]["subject"] == "s1"

        decision = resolve_approval(first["request_id"], approve=True, note="ok")
        assert decision["ok"] is True and decision["status"] == "approved"

        again = request_approval(subject="s1", risk_reason="r")
        assert again["status"] == "approved" and again["reused"] is True

    def test_reject_stays_closed(self, temp_workspace: Path, hitl_on: None) -> None:
        first = request_approval(subject="s2", risk_reason="r")
        assert resolve_approval(first["request_id"], approve=False)["status"] == "rejected"
        again = request_approval(subject="s2", risk_reason="r")
        assert again["status"] == "rejected" and again["reused"] is True

    def test_resolve_unknown_or_decided_rejected(self, temp_workspace: Path, hitl_on: None) -> None:
        assert resolve_approval("hitl_missing", approve=True)["ok"] is False
        first = request_approval(subject="s3", risk_reason="r")
        assert resolve_approval(first["request_id"], approve=True)["ok"] is True
        # Already decided — a second resolution must not flip it.
        second = resolve_approval(first["request_id"], approve=False)
        assert second["ok"] is False and second["error"].startswith("not_pending")

    def test_ttl_expiry_fails_safe_to_reject(self, temp_workspace: Path, hitl_on: None) -> None:
        import datetime

        first = request_approval(subject="s4", risk_reason="r", ttl_ms=1)
        assert first["status"] == "pending"

        from evolver.gep import hitl as hitl_mod

        future = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=5)
        original = hitl_mod._utcnow
        try:
            hitl_mod._utcnow = lambda: future  # type: ignore[assignment]
            expired = request_approval(subject="s4", risk_reason="r")
        finally:
            hitl_mod._utcnow = original  # type: ignore[assignment]

        assert expired["status"] == "rejected"
        assert "expired" in hitl_journal_path().read_text(encoding="utf-8")
