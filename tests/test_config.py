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
