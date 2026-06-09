"""Tests for evolver.adapters.auth."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Response

from evolver.adapters.auth import (
    clear_auth,
    load_auth,
    login,
    logout,
    save_auth,
    start_device_flow,
    poll_for_token,
)


@pytest.fixture(autouse=True)
def _isolate_auth_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evolver"))


class TestLoadSaveAuth:
    def test_round_trip(self) -> None:
        data = {"access_token": "tok", "expires_at": time.time() + 3600}
        save_auth(data)
        loaded = load_auth()
        assert loaded is not None
        assert loaded["access_token"] == "tok"

    def test_expired_returns_none(self) -> None:
        data = {"access_token": "tok", "expires_at": time.time() - 10}
        save_auth(data)
        assert load_auth() is None

    def test_missing_returns_none(self) -> None:
        assert load_auth() is None

    def test_clear_auth(self) -> None:
        save_auth({"access_token": "x"})
        assert clear_auth() is True
        assert clear_auth() is False


class TestLogout:
    def test_logout_when_present(self) -> None:
        save_auth({"access_token": "x"})
        result = logout()
        assert result["ok"] is True
        assert result["was_present"] is True

    def test_logout_when_absent(self) -> None:
        result = logout()
        assert result["ok"] is True
        assert result["was_present"] is False


class TestStartDeviceFlow:
    @respx.mock
    async def test_success(self) -> None:
        route = respx.post("https://evomap.ai/v1/auth/device").mock(
            return_value=Response(
                200,
                json={
                    "device_code": "dc123",
                    "user_code": "UC123",
                    "verification_uri": "https://evomap.ai/verify",
                    "expires_in": 600,
                    "interval": 1,
                },
            )
        )
        result = await start_device_flow()
        assert result["ok"] is True
        assert result["device_code"] == "dc123"
        assert result["user_code"] == "UC123"
        assert route.called

    @respx.mock
    async def test_hub_error(self) -> None:
        respx.post("https://evomap.ai/v1/auth/device").mock(return_value=Response(500))
        result = await start_device_flow()
        assert result["ok"] is False
        assert "500" in result["error"] or "Server error" in result["error"]


class TestPollForToken:
    @respx.mock
    async def test_success_on_first_try(self) -> None:
        respx.post("https://evomap.ai/v1/auth/token").mock(
            return_value=Response(
                200,
                json={"access_token": "atok", "token_type": "Bearer", "expires_in": 3600},
            )
        )
        result = await poll_for_token("dc", interval=0, expires_in=10)
        assert result["ok"] is True
        assert result["access_token"] == "atok"

    @respx.mock
    async def test_pending_then_success(self) -> None:
        calls: list[Any] = []

        def side_effect(request: Any) -> Response:
            calls.append(1)
            if len(calls) < 3:
                return Response(400, json={"error": "authorization_pending"})
            return Response(
                200,
                json={"access_token": "atok", "token_type": "Bearer", "expires_in": 3600},
            )

        respx.post("https://evomap.ai/v1/auth/token").mock(side_effect=side_effect)
        result = await poll_for_token("dc", interval=0, expires_in=10)
        assert result["ok"] is True
        assert result["access_token"] == "atok"
        assert len(calls) == 3

    @respx.mock
    async def test_expires(self) -> None:
        respx.post("https://evomap.ai/v1/auth/token").mock(
            return_value=Response(400, json={"error": "authorization_pending"})
        )
        result = await poll_for_token("dc", interval=0, expires_in=1)
        assert result["ok"] is False
        assert "expired" in result["error"].lower()


class TestLoginIntegration:
    async def test_login_mock(self) -> None:
        result = await login(mock=True)
        assert result["ok"] is True
        assert result["access_token"].startswith("mock_")
        loaded = load_auth()
        assert loaded is not None
        assert loaded["access_token"] == result["access_token"]

    @respx.mock
    async def test_login_full_flow(self, capsys: pytest.CaptureFixture[str]) -> None:
        respx.post("https://evomap.ai/v1/auth/device").mock(
            return_value=Response(
                200,
                json={
                    "device_code": "dc",
                    "user_code": "UC",
                    "verification_uri": "https://evomap.ai/verify",
                    "expires_in": 10,
                    "interval": 0,
                },
            )
        )
        respx.post("https://evomap.ai/v1/auth/token").mock(
            return_value=Response(
                200,
                json={"access_token": "real", "token_type": "Bearer", "expires_in": 3600},
            )
        )
        result = await login()
        assert result["ok"] is True
        assert result["access_token"] == "real"
        loaded = load_auth()
        assert loaded is not None
        assert loaded["access_token"] == "real"
        captured = capsys.readouterr()
        assert "evomap.ai/verify" in captured.out
        assert "UC" in captured.out
