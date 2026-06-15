"""Tests for evolver.proxy.router.features."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.proxy.router.features import (
    FEATURE_FLAG_REFRESH_INTERVAL,
    get_disabled_routes,
    is_route_enabled,
    refresh_feature_flags,
)


class TestRefreshFeatureFlags:
    def test_returns_dict(self):
        flags = refresh_feature_flags()
        assert isinstance(flags, dict)
        assert "enable_validator" in flags

    def test_defaults(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("EVOLVER_FF_ENABLE_LLM_REVIEW", raising=False)
        flags = refresh_feature_flags()
        assert flags["enable_validator"] is True
        assert flags["enable_llm_review"] is True
        assert flags["enable_skill_auto_update"] is False

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EVOLVER_FF_enable_llm_review", "1")
        flags = refresh_feature_flags()
        assert flags["enable_llm_review"] is True

    def test_env_false_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EVOLVER_FF_enable_validator", "false")
        flags = refresh_feature_flags()
        assert flags["enable_validator"] is False

    def test_disk_flags(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        from evolver.gep.feature_flags import invalidate_cache

        flag_file = tmp_path / "feature_flags.json"
        flag_file.write_text(json.dumps({"enable_explore": True}), encoding="utf-8")
        monkeypatch.setenv("EVOMAP_FEATURE_FLAGS_PATH", str(flag_file))
        invalidate_cache()
        flags = refresh_feature_flags()
        assert flags["enable_explore"] is True


class TestIsRouteEnabled:
    def test_known_route(self):
        # Validator is enabled by default
        assert is_route_enabled("validator_tasks") is True

    def test_disabled_route(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EVOLVER_FF_enable_validator", "false")
        assert is_route_enabled("validator_tasks") is False

    def test_unknown_route_defaults_enabled(self):
        assert is_route_enabled("some_new_route") is True

    def test_llm_review_enabled_by_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("EVOLVER_FF_ENABLE_LLM_REVIEW", raising=False)
        assert is_route_enabled("llm_messages") is True


class TestGetDisabledRoutes:
    def test_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("EVOLVER_FF_ENABLE_LLM_REVIEW", raising=False)
        monkeypatch.delenv("EVOLVER_FF_ENABLE_AUTO_BUYER", raising=False)
        disabled = get_disabled_routes()
        assert "llm_messages" not in disabled
        assert "atp_order" in disabled

    def test_after_enable(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EVOLVER_FF_enable_llm_review", "true")
        monkeypatch.setenv("EVOLVER_FF_enable_auto_buyer", "true")
        disabled = get_disabled_routes()
        assert "llm_messages" not in disabled
        assert "atp_order" not in disabled


class TestRefreshInterval:
    def test_interval_positive(self):
        assert FEATURE_FLAG_REFRESH_INTERVAL > 0
