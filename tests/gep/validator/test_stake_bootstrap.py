"""Tests for evolver.gep.validator.stake_bootstrap."""

import time
from unittest.mock import patch

import pytest

from evolver.gep.validator.stake_bootstrap import (
    StakeRequest,
    StakeState,
    format_instructions,
    generate_stake_request,
    is_staked,
    load_stake_state,
    save_stake_state,
    wait_for_confirmation,
)


class TestStakeRequest:
    def test_defaults(self):
        req = generate_stake_request(node_id="n1")
        assert req.node_id == "n1"
        assert req.amount > 0
        assert req.memo

    def test_custom_amount(self):
        req = generate_stake_request(node_id="n1", amount=500.0)
        assert req.amount == 500.0


class TestFormatInstructions:
    def test_contains_node_id(self):
        req = generate_stake_request(node_id="n1")
        text = format_instructions(req)
        assert "n1" in text
        assert str(req.amount) in text


class TestStakeState:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "state.json"
        state = StakeState(node_id="n1", status="pending", created_at=time.time())
        save_stake_state(state)
        loaded = load_stake_state()
        # Uses workspace root, not tmp_path — test path override
        with patch("evolver.gep.validator.stake_bootstrap._state_path", return_value=path):
            save_stake_state(state)
            loaded = load_stake_state()
        assert loaded is not None
        assert loaded.node_id == "n1"
        assert loaded.status == "pending"

    def test_missing(self, tmp_path):
        with patch("evolver.gep.validator.stake_bootstrap._state_path", return_value=tmp_path / "missing.json"):
            assert load_stake_state() is None


class TestIsStaked:
    def test_confirmed(self, tmp_path):
        state = StakeState(node_id="n1", status="confirmed")
        with patch("evolver.gep.validator.stake_bootstrap._state_path", return_value=tmp_path / "state.json"):
            save_stake_state(state)
            assert is_staked()

    def test_pending(self, tmp_path):
        state = StakeState(node_id="n1", status="pending")
        with patch("evolver.gep.validator.stake_bootstrap._state_path", return_value=tmp_path / "state.json"):
            save_stake_state(state)
            assert not is_staked()

    def test_none(self, tmp_path):
        with patch("evolver.gep.validator.stake_bootstrap._state_path", return_value=tmp_path / "missing.json"):
            assert not is_staked()


class TestWaitForConfirmation:
    def test_already_confirmed(self, tmp_path):
        state = StakeState(node_id="n1", status="confirmed", tx_hash="abc")
        with patch("evolver.gep.validator.stake_bootstrap._state_path", return_value=tmp_path / "state.json"):
            save_stake_state(state)
            result = wait_for_confirmation("n1", poll_interval=0.1, max_attempts=1)
        assert result.status == "confirmed"

    def test_timeout(self, tmp_path):
        with patch("evolver.gep.validator.stake_bootstrap._query_stake_status", return_value=None):
            with patch("evolver.gep.validator.stake_bootstrap._state_path", return_value=tmp_path / "state.json"):
                result = wait_for_confirmation("n1", poll_interval=0.1, max_attempts=2)
        assert result.status == "pending"

    def test_confirmed_during_poll(self, tmp_path):
        with patch("evolver.gep.validator.stake_bootstrap._query_stake_status", return_value={"status": "confirmed", "tx_hash": "abc"}):
            with patch("evolver.gep.validator.stake_bootstrap._state_path", return_value=tmp_path / "state.json"):
                result = wait_for_confirmation("n1", poll_interval=0.1, max_attempts=2)
        assert result.status == "confirmed"
        assert result.tx_hash == "abc"
