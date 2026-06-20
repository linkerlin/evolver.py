"""Tests for evolver.config — equivalent to evolver/test/config.test.js."""

from __future__ import annotations

import pytest

from evolver import config


def test_env_int_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_INT", raising=False)
    assert config.env_int("TEST_INT", 42) == 42


def test_env_int_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_INT", "7")
    assert config.env_int("TEST_INT", 42) == 7


def test_env_int_invalid_returns_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_INT", "abc")
    assert config.env_int("TEST_INT", 42) == 42


def test_env_positive_int_rejects_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_POS", "0")
    assert config.env_positive_int("TEST_POS", 100) == 100


def test_env_positive_int_rejects_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_POS", "-5")
    assert config.env_positive_int("TEST_POS", 100) == 100


def test_resolve_hub_url_default() -> None:
    assert config.resolve_hub_url() == config.PUBLIC_DEFAULT_HUB_URL


def test_resolve_hub_url_allows_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "https://private.example.com")
    assert config.resolve_hub_url() == "https://private.example.com"


def test_resolve_hub_url_rejects_http_without_insecure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "http://insecure.example.com")
    with pytest.raises(ValueError):
        config.resolve_hub_url()


def test_resolve_hub_url_allows_http_with_insecure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("A2A_HUB_URL", "http://insecure.example.com")
    monkeypatch.setenv("EVOMAP_HUB_ALLOW_INSECURE", "1")
    assert config.resolve_hub_url() == "http://insecure.example.com"


def test_resolve_proxy_port_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOLVER_PROXY_PORT", raising=False)
    monkeypatch.delenv("EVOMAP_PROXY_PORT", raising=False)
    assert config.resolve_proxy_port() == config.DEFAULT_PROXY_PORT == 8081


def test_resolve_proxy_port_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_PROXY_PORT", "9090")
    assert config.resolve_proxy_port() == 9090


def test_resolve_webui_port_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOLVER_WEBUI_PORT", raising=False)
    assert config.resolve_webui_port() == config.DEFAULT_WEBUI_PORT == 8080


def test_resolve_webui_port_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLVER_WEBUI_PORT", "3000")
    assert config.resolve_webui_port() == 3000


def test_proxy_local_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOLVER_PROXY_PORT", raising=False)
    monkeypatch.delenv("EVOMAP_PROXY_PORT", raising=False)
    url = config.proxy_local_url("v1/messages")
    assert url.endswith("/v1/a2a/v1/messages")
    assert ":8081" in url


# ---------------------------------------------------------------------------
# Gap 4+5: Anti-abuse telemetry mode + Outcome report mode
# ---------------------------------------------------------------------------


def test_anti_abuse_telemetry_mode_default_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOLVER_ANTI_ABUSE_TELEMETRY", raising=False)
    assert config.anti_abuse_telemetry_mode() == "heartbeat"


def test_anti_abuse_telemetry_mode_empty_is_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty value counts as UNSET — default-on behavior preserved."""
    monkeypatch.setenv("EVOLVER_ANTI_ABUSE_TELEMETRY", "")
    assert config.anti_abuse_telemetry_mode() == "heartbeat"


def test_anti_abuse_telemetry_mode_explicit_off(monkeypatch: pytest.MonkeyPatch) -> None:
    for v in ("0", "false", "no", "off"):
        monkeypatch.setenv("EVOLVER_ANTI_ABUSE_TELEMETRY", v)
        assert config.anti_abuse_telemetry_mode() == "off"


def test_outcome_report_mode_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVOLVER_OUTCOME_REPORT", raising=False)
    assert config.outcome_report_mode() == "off"


def test_outcome_report_mode_on(monkeypatch: pytest.MonkeyPatch) -> None:
    for v in ("on", "enforce", "true"):
        monkeypatch.setenv("EVOLVER_OUTCOME_REPORT", v)
        assert config.outcome_report_mode() == "on"
