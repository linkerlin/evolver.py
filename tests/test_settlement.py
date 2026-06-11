"""Tests for evolver.atp.settlement."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.atp.settlement import _load_ledger, credit, debit, get_balance, history


@pytest.fixture(autouse=True)
def _isolate_ledger(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evolver"))


class TestBalance:
    def test_initial_zero(self) -> None:
        result = get_balance()
        assert result["ok"] is True
        assert result["balance"] == 0.0


class TestCredit:
    def test_credit_increases_balance(self) -> None:
        result = credit(100.0, "test")
        assert result["ok"] is True
        assert result["balance"] == 100.0

    def test_credit_negative_rejected(self) -> None:
        result = credit(-10.0)
        assert result["ok"] is False

    def test_credit_zero_rejected(self) -> None:
        result = credit(0.0)
        assert result["ok"] is False


class TestDebit:
    def test_debit_decreases_balance(self) -> None:
        credit(100.0)
        result = debit(30.0, "purchase")
        assert result["ok"] is True
        assert result["balance"] == 70.0

    def test_debit_overdraft_rejected(self) -> None:
        result = debit(10.0)
        assert result["ok"] is False
        assert "insufficient" in result["error"].lower()

    def test_debit_negative_rejected(self) -> None:
        result = debit(-5.0)
        assert result["ok"] is False


class TestHistory:
    def test_records_transactions(self) -> None:
        credit(50.0, "bonus")
        debit(10.0, "fee")
        result = history(limit=10)
        assert result["ok"] is True
        assert len(result["transactions"]) == 2
        kinds = [t["kind"] for t in result["transactions"]]
        assert "debit" in kinds
        assert "credit" in kinds

    def test_respects_limit(self) -> None:
        for i in range(5):
            credit(1.0, f"tx{i}")
        result = history(limit=3)
        assert len(result["transactions"]) == 3


class TestPersistence:
    def test_round_trip(self) -> None:
        credit(42.0)
        ledger = _load_ledger()
        assert ledger["balance"] == 42.0
        assert len(ledger["transactions"]) == 1
