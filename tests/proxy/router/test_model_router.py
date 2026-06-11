"""Tests for evolver.proxy.router.model_router."""

from __future__ import annotations

import os

import pytest

from evolver.proxy.router.model_router import (
    DEFAULT_MODEL_FALLBACKS,
    get_upstream_preference,
    resolve_model,
    select_upstream_for_model,
)


class TestGetUpstreamPreference:
    def test_default_is_anthropic(self):
        os.environ.pop("EVOMAP_UPSTREAM", None)
        assert get_upstream_preference() == "anthropic"

    def test_env_anthropic(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EVOMAP_UPSTREAM", "anthropic")
        assert get_upstream_preference() == "anthropic"

    def test_env_bedrock(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EVOMAP_UPSTREAM", "bedrock")
        assert get_upstream_preference() == "bedrock"

    def test_env_case_insensitive(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EVOMAP_UPSTREAM", "Bedrock")
        assert get_upstream_preference() == "bedrock"

    def test_invalid_env_falls_back(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EVOMAP_UPSTREAM", "openai")
        assert get_upstream_preference() == "anthropic"


class TestResolveModel:
    def test_basic_resolution(self):
        result = resolve_model(requested_model="claude-3-5-sonnet")
        assert result["model"] == "claude-3-5-sonnet"
        assert result["upstream"] == "anthropic"
        assert result["tier"] == "mid"
        assert len(result["fallback_chain"]) >= 1

    def test_tier_hint(self):
        result = resolve_model(requested_model="claude-3-opus", tier_hint="expensive")
        assert result["tier"] == "expensive"

    def test_invalid_tier_defaults_to_mid(self):
        result = resolve_model(tier_hint="luxury")
        assert result["tier"] == "mid"

    def test_force_upstream(self):
        result = resolve_model(
            requested_model="claude-3-5-sonnet",
            feature_flags={"force_upstream": "bedrock"},
        )
        assert result["upstream"] == "bedrock"

    def test_user_tier_downgrade_protection(self):
        result = resolve_model(
            requested_model="claude-3-opus",
            tier_hint="cheap",
            feature_flags={"user_tier": "premium"},
        )
        assert result["tier"] == "mid"

    def test_fallback_chain(self):
        result = resolve_model(requested_model="claude-3-7-sonnet")
        chain = result["fallback_chain"]
        assert "claude-3-5-sonnet" in chain

    def test_default_model(self):
        result = resolve_model()
        assert result["model"] == "claude-3-5-sonnet"


class TestSelectUpstreamForModel:
    def test_bedrock_prefix(self):
        assert select_upstream_for_model("anthropic.claude-3") == "bedrock"

    def test_bedrock_in_name(self):
        assert select_upstream_for_model("claude-bedrock-model") == "bedrock"

    def test_anthropic_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("EVOMAP_UPSTREAM", "anthropic")
        assert select_upstream_for_model("claude-3-5-sonnet") == "anthropic"

    def test_default_fallback(self):
        os.environ.pop("EVOMAP_UPSTREAM", None)
        assert select_upstream_for_model("claude-3-5-sonnet") == "anthropic"


class TestDefaultModelFallbacks:
    def test_known_mappings(self):
        assert "claude-3-5-sonnet" in DEFAULT_MODEL_FALLBACKS["claude-3-7-sonnet"]
        assert "claude-3-5-sonnet" in DEFAULT_MODEL_FALLBACKS["claude-3-opus"]
