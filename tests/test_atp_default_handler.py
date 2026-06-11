"""Tests for evolver.atp.default_handler."""

from __future__ import annotations

import json

import pytest

from evolver.atp.default_handler import (
    default_order_handler,
    get_atp_mode,
    resolve_atp_services,
)


class TestDefaultOrderHandler:
    def test_review_order(self) -> None:
        result = default_order_handler({"title": "Code review for PR", "signals": ""})
        assert result["result"] == "Code review processed by evolver. Analysis complete."
        assert result["pass_rate"] == 1.0
        assert result["processor"] == "evolver-default"
        assert "processed_at" in result

    def test_bug_signal(self) -> None:
        result = default_order_handler({"title": "", "signals": "bug report"})
        assert "Code review" in result["result"]

    def test_translation(self) -> None:
        result = default_order_handler({"title": "Translate docs", "signals": ""})
        assert "Translation" in result["result"]

    def test_localization_signal(self) -> None:
        result = default_order_handler({"title": "", "signals": "localization"})
        assert "Translation" in result["result"]

    def test_summarization(self) -> None:
        result = default_order_handler({"title": "Summarize meeting", "signals": ""})
        assert "Summarization" in result["result"]

    def test_digest_signal(self) -> None:
        result = default_order_handler({"title": "", "signals": "digest"})
        assert "Summarization" in result["result"]

    def test_generic_task(self) -> None:
        result = default_order_handler({"title": "Build feature", "signals": ""})
        assert result["result"] == "Task processed by evolver agent."

    def test_output_equals_result(self) -> None:
        result = default_order_handler({"title": "x", "signals": ""})
        assert result["output"] == result["result"]


class TestResolveAtpServices:
    def test_from_env_json(self) -> None:
        env = {"EVOLVER_ATP_SERVICES": json.dumps([{"title": "Custom"}])}
        services = resolve_atp_services(env)
        assert services == [{"title": "Custom"}]

    def test_from_env_invalid_json_uses_default(self) -> None:
        env = {"EVOLVER_ATP_SERVICES": "not-json"}
        services = resolve_atp_services(env)
        assert len(services) == 1
        assert "Code Evolution" in services[0]["title"]

    def test_from_env_empty_list_uses_default(self) -> None:
        env = {"EVOLVER_ATP_SERVICES": "[]"}
        services = resolve_atp_services(env)
        assert len(services) == 1
        assert "Code Evolution" in services[0]["title"]

    def test_default_uses_env_name(self) -> None:
        env = {"EVOLVER_AGENT_NAME": "MyAgent"}
        services = resolve_atp_services(env)
        assert services[0]["title"] == "MyAgent - Code Evolution"

    def test_default_uses_model_name_fallback(self) -> None:
        env = {"EVOLVER_MODEL_NAME": "GPT-4"}
        services = resolve_atp_services(env)
        assert services[0]["title"] == "GPT-4 - Code Evolution"

    def test_default_no_env(self) -> None:
        services = resolve_atp_services({})
        assert services[0]["title"] == "Evolver Agent - Code Evolution"
        assert services[0]["capabilities"] == [
            "code_evolution",
            "bug_fix",
            "code_review",
            "refactoring",
        ]
        assert services[0]["pricePerTask"] == 5
        assert services[0]["maxConcurrent"] == 3


class TestGetAtpMode:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("off", "off"),
            ("OFF", "off"),
            ("false", "off"),
            ("0", "off"),
            ("on", "on"),
            ("ON", "on"),
            ("true", "on"),
            ("1", "on"),
            ("auto", "auto"),
            ("AUTO", "auto"),
            ("anything_else", "auto"),
        ],
    )
    def test_modes(self, value: str, expected: str) -> None:
        assert get_atp_mode({"EVOLVER_ATP": value}) == expected

    def test_default(self) -> None:
        assert get_atp_mode({}) == "auto"
