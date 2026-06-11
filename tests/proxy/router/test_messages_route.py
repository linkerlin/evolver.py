"""Tests for evolver.proxy.router.messages_route."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import respx
from fastapi.responses import JSONResponse, StreamingResponse
from httpx import Response

from evolver.proxy.router.messages_route import (
    ANTHROPIC_API_URL,
    BEDROCK_MODEL_MAP,
    canonicalize_for_bedrock,
    proxy_anthropic,
)


class TestCanonicalizeForBedrock:
    def test_known_mapping(self):
        assert (
            canonicalize_for_bedrock("claude-3-5-sonnet-20241022")
            == BEDROCK_MODEL_MAP["claude-3-5-sonnet-20241022"]
        )

    def test_unknown_returns_as_is(self):
        assert canonicalize_for_bedrock("custom-model") == "custom-model"

    def test_all_mappings_present(self):
        for anthropic_id, bedrock_id in BEDROCK_MODEL_MAP.items():
            assert canonicalize_for_bedrock(anthropic_id) == bedrock_id
            assert bedrock_id.startswith("anthropic.")


class TestBedrockBodyTransform:
    def test_removes_stream(self):
        from evolver.proxy.router.messages_route import _bedrock_body_transform

        body = {"model": "claude-3", "messages": [], "stream": True}
        result = _bedrock_body_transform(body)
        assert "stream" not in result

    def test_sets_max_tokens_default(self):
        from evolver.proxy.router.messages_route import _bedrock_body_transform

        body = {"model": "claude-3", "messages": []}
        result = _bedrock_body_transform(body)
        assert result["max_tokens"] == 4096

    def test_preserves_system(self):
        from evolver.proxy.router.messages_route import _bedrock_body_transform

        body = {"model": "claude-3", "messages": [], "system": "You are a test bot"}
        result = _bedrock_body_transform(body)
        assert result["system"] == "You are a test bot"

    def test_adaptive_thinking_downgrade(self):
        from evolver.proxy.router.messages_route import _bedrock_body_transform

        body = {
            "model": "claude-3",
            "messages": [],
            "thinking": {"type": "adaptive", "budget_tokens": 1024},
        }
        result = _bedrock_body_transform(body)
        assert result["thinking"]["type"] == "enabled"
        assert result["thinking"]["budget_tokens"] == 1024

    def test_zero_budget_adaptive_becomes_disabled(self):
        from evolver.proxy.router.messages_route import _bedrock_body_transform

        body = {
            "model": "claude-3",
            "messages": [],
            "thinking": {"type": "adaptive", "budget_tokens": 0},
        }
        result = _bedrock_body_transform(body)
        assert result["thinking"]["type"] == "disabled"


class TestAnthropicBodyTransform:
    def test_adds_max_tokens(self):
        from evolver.proxy.router.messages_route import _anthropic_body_transform

        body = {"model": "claude-3", "messages": []}
        result = _anthropic_body_transform(body)
        assert result["max_tokens"] == 4096

    def test_preserves_existing_max_tokens(self):
        from evolver.proxy.router.messages_route import _anthropic_body_transform

        body = {"model": "claude-3", "messages": [], "max_tokens": 2048}
        result = _anthropic_body_transform(body)
        assert result["max_tokens"] == 2048


class TestAnthropicStreaming:
    @pytest.mark.asyncio
    @respx.mock
    async def test_stream_returns_streaming_response(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        sse = b"event: message_start\ndata: {}\n\n"
        respx.post(ANTHROPIC_API_URL).mock(
            return_value=Response(200, content=sse, headers={"content-type": "text/event-stream"})
        )
        request = MagicMock()
        body = {"model": "claude-3-5-sonnet-20241022", "messages": [], "stream": True}
        response = await proxy_anthropic(request, body)
        assert isinstance(response, StreamingResponse)
        chunks = [chunk async for chunk in response.body_iterator]
        assert b"message_start" in b"".join(chunks)

    @pytest.mark.asyncio
    async def test_stream_missing_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        request = MagicMock()
        body = {"model": "claude-3", "messages": [], "stream": True}
        response = await proxy_anthropic(request, body)
        assert isinstance(response, JSONResponse)
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_bedrock_stream_returns_streaming_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _FakeBody:
            def __iter__(self):
                yield {"chunk": {"bytes": b'{"type":"message_start"}'}}

        class _FakeClient:
            def invoke_model_with_response_stream(self, **kwargs: object) -> dict[str, object]:
                return {"body": _FakeBody()}

        monkeypatch.setattr("boto3.client", lambda *args, **kwargs: _FakeClient())

        from evolver.proxy.router.messages_route import _proxy_bedrock_stream

        response = await _proxy_bedrock_stream(
            "anthropic.claude-3-5-sonnet-20241022-v1:0",
            {"messages": [], "max_tokens": 1024},
        )
        assert isinstance(response, StreamingResponse)
        chunks = [chunk async for chunk in response.body_iterator]
        assert b"message_start" in b"".join(chunks)
