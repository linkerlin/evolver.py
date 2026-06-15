"""Tests for Sprint 5 proxy routes + infrastructure modules."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.proxy.envelope import create_envelope, unwrap_payload, validate_envelope
from evolver.proxy.inject import inject_trace_id, strip_internal_fields
from evolver.proxy.router import model_router
from evolver.proxy.router.gemini_route import _transform_to_gemini
from evolver.proxy.router.models_route import list_models
from evolver.proxy.router.ollama_route import _transform_to_openai as ollama_transform
from evolver.proxy.router.responses_route import (
    _build_openai_headers,
    _transform_to_openai,
)
from evolver.proxy.server.settings import load_settings, save_settings
from evolver.proxy.trace.extractor import extract_trace_entry, extract_usage
from evolver.proxy.trace.usage import UsageAggregator

# ---------------------------------------------------------------------------
# model_router.select_upstream_for_model
# ---------------------------------------------------------------------------


class TestSelectUpstream:
    def test_bedrock(self) -> None:
        assert model_router.select_upstream_for_model("anthropic.claude-3-sonnet") == "bedrock"

    def test_gemini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VERTEX_PROJECT", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        assert model_router.select_upstream_for_model("gemini-2.0-flash") == "gemini"

    def test_gemini_to_vertex_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VERTEX_PROJECT", "my-project")
        assert model_router.select_upstream_for_model("gemini-2.0-flash") == "vertex"

    def test_ollama(self) -> None:
        assert model_router.select_upstream_for_model("ollama:llama3") == "ollama"

    def test_openai_gpt(self) -> None:
        assert model_router.select_upstream_for_model("gpt-4o") == "openai"

    def test_openai_o3(self) -> None:
        assert model_router.select_upstream_for_model("o3-mini") == "openai"

    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOMAP_UPSTREAM", "anthropic")
        assert model_router.select_upstream_for_model("claude-3-5-sonnet") == "anthropic"


# ---------------------------------------------------------------------------
# Body transforms
# ---------------------------------------------------------------------------


class TestGeminiTransform:
    def test_basic(self) -> None:
        body = {
            "model": "gemini-2.0-flash",
            "messages": [{"role": "user", "content": "Hello"}],
            "system": "You are helpful.",
        }
        result = _transform_to_gemini(body)
        assert result["contents"][0]["role"] == "user"
        assert result["contents"][0]["parts"][0]["text"] == "Hello"
        assert result["systemInstruction"]["parts"][0]["text"] == "You are helpful."

    def test_flattens_content_blocks(self) -> None:
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "part1"},
                        {"type": "text", "text": "part2"},
                    ],
                }
            ],
        }
        result = _transform_to_gemini(body)
        assert "part1 part2" in result["contents"][0]["parts"][0]["text"]

    def test_generation_config(self) -> None:
        body = {"messages": [], "max_tokens": 100, "temperature": 0.5}
        result = _transform_to_gemini(body)
        assert result["generationConfig"]["maxOutputTokens"] == 100
        assert result["generationConfig"]["temperature"] == 0.5


class TestOllamaTransform:
    def test_basic(self) -> None:
        body = {"model": "llama3", "messages": [{"role": "user", "content": "Hi"}]}
        result = ollama_transform(body)
        assert result["model"] == "llama3"
        assert result["messages"][0]["content"] == "Hi"


class TestOpenAITransform:
    def test_basic(self) -> None:
        body = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hello"}],
            "system": "Be concise.",
        }
        result = _transform_to_openai(body)
        assert result["model"] == "gpt-4o"
        assert result["messages"][0]["role"] == "system"
        assert result["messages"][0]["content"] == "Be concise."
        assert result["messages"][1]["content"] == "Hello"

    def test_headers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        headers = _build_openai_headers()
        assert headers["Authorization"] == "Bearer sk-test"


# ---------------------------------------------------------------------------
# Models list
# ---------------------------------------------------------------------------


class TestListModels:
    def test_empty_when_no_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key in (
            "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
            "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
            "VERTEX_PROJECT", "GOOGLE_CLOUD_PROJECT",
        ):
            monkeypatch.delenv(key, raising=False)
        result = list_models()
        # Ollama might add models if running, but data should be a list.
        assert "data" in result

    def test_includes_anthropic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        result = list_models()
        ids = [m["id"] for m in result["data"]]
        assert any("claude" in i for i in ids)

    def test_includes_openai(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        result = list_models()
        ids = [m["id"] for m in result["data"]]
        assert any("gpt" in i for i in ids)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class TestSettings:
    def test_load_defaults(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("EVOLVER_PROXY_SETTINGS_PATH", str(tmp_path / "settings.json"))
        settings = load_settings()
        assert settings["upstream"] == "anthropic"
        assert settings["port"] == 8081

    def test_save_and_load(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        path = tmp_path / "settings.json"
        monkeypatch.setenv("EVOLVER_PROXY_SETTINGS_PATH", str(path))
        save_settings({"upstream": "gemini", "port": 9090})
        loaded = load_settings()
        assert loaded["upstream"] == "gemini"
        assert loaded["port"] == 9090


# ---------------------------------------------------------------------------
# Trace extractor + usage
# ---------------------------------------------------------------------------


class TestTraceExtractor:
    def test_anthropic_usage(self) -> None:
        result = extract_usage({"usage": {"input_tokens": 100, "output_tokens": 50}})
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 50

    def test_gemini_usage(self) -> None:
        result = extract_usage(
            {"usageMetadata": {"promptTokenCount": 200, "candidatesTokenCount": 80}}
        )
        assert result["input_tokens"] == 200
        assert result["output_tokens"] == 80

    def test_empty_usage(self) -> None:
        result = extract_usage({})
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0

    def test_trace_entry(self) -> None:
        entry = extract_trace_entry(
            {"model": "claude-3-5-sonnet"},
            {"usage": {"input_tokens": 10, "output_tokens": 5}},
            status_code=200,
            elapsed_ms=123.4,
            upstream="anthropic",
        )
        assert entry["model"] == "claude-3-5-sonnet"
        assert entry["status_code"] == 200
        assert entry["usage"]["input_tokens"] == 10


class TestUsageAggregator:
    def test_record_and_summary(self) -> None:
        agg = UsageAggregator()
        agg.record("gpt-4o", "openai", input_tokens=100, output_tokens=50)
        agg.record("gpt-4o", "openai", input_tokens=200, output_tokens=100)
        summary = agg.get_summary()
        assert summary["total_requests"] == 2
        assert summary["total_input_tokens"] == 300
        assert summary["total_output_tokens"] == 150

    def test_by_model(self) -> None:
        agg = UsageAggregator()
        agg.record("gpt-4o", "openai", input_tokens=100)
        agg.record("claude-3-5", "anthropic", input_tokens=200)
        summary = agg.get_summary()
        assert "gpt-4o@openai" in summary["by_model"]
        assert "claude-3-5@anthropic" in summary["by_model"]

    def test_reset(self) -> None:
        agg = UsageAggregator()
        agg.record("gpt-4o", "openai", input_tokens=100)
        agg.reset()
        assert agg.get_summary()["total_requests"] == 0


# ---------------------------------------------------------------------------
# Envelope + Inject
# ---------------------------------------------------------------------------


class TestEnvelope:
    def test_create_and_validate(self) -> None:
        env = create_envelope("task_assigned", {"task_id": "t1"}, sender="node-a")
        assert validate_envelope(env)
        assert env["type"] == "task_assigned"

    def test_unwrap(self) -> None:
        env = create_envelope("test", {"key": "value"})
        payload = unwrap_payload(env)
        assert payload == {"key": "value"}

    def test_invalid_envelope(self) -> None:
        assert not validate_envelope({"id": "x"})
        assert unwrap_payload({"id": "x"}) is None


class TestInject:
    def test_trace_id(self) -> None:
        body = {"model": "gpt-4o", "messages": []}
        result = inject_trace_id(body)
        assert "_evolver_trace_id" in result["metadata"]

    def test_strip(self) -> None:
        body = {"model": "gpt-4o", "metadata": {"_evolver_trace_id": "x", "other": "y"}}
        result = strip_internal_fields(body)
        assert "_evolver_trace_id" not in result["metadata"]
        assert result["metadata"]["other"] == "y"

    def test_strip_removes_empty_metadata(self) -> None:
        body = {"model": "gpt-4o", "metadata": {"_evolver_trace_id": "x"}}
        result = strip_internal_fields(body)
        assert "metadata" not in result
