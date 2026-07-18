"""Sprint 15.1 — multi-provider proxy E2E (models / gemini / ollama / vertex / openai).

Uses a real FastAPI TestClient (socketless ASGI) + respx-mocked upstreams so we
assert routing, error mapping, and byte-level JSON passthrough without live keys.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from evolver.proxy.router.model_router import select_upstream_for_model
from evolver.proxy.router.models_route import list_models
from evolver.proxy.server.routes import router

TOKEN = "a" * 64


@pytest.fixture
def proxy_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("EVOMAP_PROXY_TOKEN", TOKEN)
    monkeypatch.setenv("EVOLVER_PROXY_LIFECYCLE", "0")
    app = FastAPI()
    app.include_router(router, prefix="/v1/a2a")
    with TestClient(app) as client:
        yield client


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _anthropic_body(model: str, *, stream: bool = False) -> dict[str, Any]:
    return {
        "model": model,
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "hi"}],
        "stream": stream,
    }


# ---------------------------------------------------------------------------
# Routing matrix
# ---------------------------------------------------------------------------


class TestUpstreamSelection:
    def test_gemini_prefix(self) -> None:
        assert select_upstream_for_model("gemini-2.0-flash") == "gemini"

    def test_vertex_prefix(self) -> None:
        assert select_upstream_for_model("vertex-gemini-1.5-pro") == "vertex"

    def test_ollama_prefix(self) -> None:
        assert select_upstream_for_model("ollama:llama3") == "ollama"

    def test_openai_gpt(self) -> None:
        assert select_upstream_for_model("gpt-4o") == "openai"

    def test_openai_o_series(self) -> None:
        assert select_upstream_for_model("o3-mini") == "openai"

    def test_bedrock_anthropic_dot(self) -> None:
        assert select_upstream_for_model("anthropic.claude-3-5-sonnet") == "bedrock"

    def test_gemini_with_vertex_project(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VERTEX_PROJECT", "my-proj")
        assert select_upstream_for_model("gemini-2.0-flash") == "vertex"


# ---------------------------------------------------------------------------
# Models route
# ---------------------------------------------------------------------------


class TestModelsE2E:
    def test_list_models_openai_schema(
        self, proxy_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("GEMINI_API_KEY", "gk-test")
        monkeypatch.delenv("VERTEX_PROJECT", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        res = proxy_client.get("/v1/a2a/v1/models", headers=_auth())
        assert res.status_code == 200
        body = res.json()
        assert body["object"] == "list"
        assert isinstance(body["data"], list)
        assert len(body["data"]) >= 3
        owners = {m["owned_by"] for m in body["data"]}
        assert "anthropic" in owners
        assert "openai" in owners
        assert "google" in owners
        for m in body["data"]:
            assert "id" in m and "object" in m

    def test_list_models_requires_auth(self, proxy_client: TestClient) -> None:
        res = proxy_client.get("/v1/a2a/v1/models")
        assert res.status_code == 401

    def test_list_models_helper_empty_without_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for k in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "VERTEX_PROJECT",
            "GOOGLE_CLOUD_PROJECT",
        ):
            monkeypatch.delenv(k, raising=False)
        data = list_models()
        assert data["object"] == "list"
        # May still include ollama if local daemon is up — accept empty or ollama-only
        assert all(m.get("owned_by") == "ollama" for m in data["data"]) or data["data"] == []


# ---------------------------------------------------------------------------
# Gemini (Anthropic-shape via /v1/messages + native path)
# ---------------------------------------------------------------------------


class TestGeminiE2E:
    @respx.mock
    def test_messages_routes_to_gemini_generate(
        self, proxy_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "gk-test")
        monkeypatch.delenv("VERTEX_PROJECT", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        route = respx.post(
            url__regex=r"https://generativelanguage\.googleapis\.com/v1beta/models/gemini-2\.0-flash:generateContent.*"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [{"text": "hi there"}],
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 12,
                        "candidatesTokenCount": 4,
                        "totalTokenCount": 16,
                    },
                },
            )
        )
        res = proxy_client.post(
            "/v1/a2a/v1/messages",
            headers=_auth(),
            json=_anthropic_body("gemini-2.0-flash"),
        )
        assert res.status_code == 200, res.text
        assert route.called
        body = res.json()
        assert body["candidates"][0]["content"]["parts"][0]["text"] == "hi there"
        assert body["usageMetadata"]["totalTokenCount"] == 16
        # Transformed body should be Gemini-shaped
        sent = json.loads(route.calls.last.request.content.decode())
        assert "contents" in sent
        assert sent["contents"][0]["role"] == "user"

    @respx.mock
    def test_native_path_passthrough(
        self, proxy_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "gk-test")
        gemini_body = {
            "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
        }
        route = respx.post(url__regex=r".*/models/gemini-2\.0-flash:generateContent.*").mock(
            return_value=httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {"role": "model", "parts": [{"text": "pong"}]},
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
                },
            )
        )
        res = proxy_client.post(
            "/v1/a2a/v1beta/models/gemini-2.0-flash:generateContent",
            headers={**_auth(), "x-goog-api-key": "client-key"},
            json=gemini_body,
        )
        assert res.status_code == 200
        assert route.called
        # Client key preferred
        assert route.calls.last.request.headers.get("x-goog-api-key") == "client-key"
        # Body forwarded without Anthropic translation
        sent = json.loads(route.calls.last.request.content.decode())
        assert sent == gemini_body
        assert res.json()["candidates"][0]["content"]["parts"][0]["text"] == "pong"

    def test_missing_key_401(
        self, proxy_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        res = proxy_client.post(
            "/v1/a2a/v1/messages",
            headers=_auth(),
            json=_anthropic_body("gemini-2.0-flash"),
        )
        assert res.status_code == 401
        assert res.json()["error"] == "missing_gemini_api_key"

    @respx.mock
    def test_upstream_5xx_maps_to_502(
        self, proxy_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "gk-test")
        monkeypatch.delenv("VERTEX_PROJECT", raising=False)
        respx.post(url__regex=r".*generativelanguage\.googleapis\.com.*").mock(
            return_value=httpx.Response(503, text="overloaded")
        )
        res = proxy_client.post(
            "/v1/a2a/v1/messages",
            headers=_auth(),
            json=_anthropic_body("gemini-2.0-flash"),
        )
        assert res.status_code == 502
        assert res.json()["error"] == "upstream_error"


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


class TestOllamaE2E:
    @respx.mock
    def test_messages_ollama_transform_and_forward(
        self, proxy_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        route = respx.post("http://127.0.0.1:11434/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "chatcmpl-ollama",
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "hello"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 2,
                        "total_tokens": 7,
                    },
                },
            )
        )
        res = proxy_client.post(
            "/v1/a2a/v1/messages",
            headers=_auth(),
            json=_anthropic_body("ollama:llama3"),
        )
        assert res.status_code == 200, res.text
        assert route.called
        sent = json.loads(route.calls.last.request.content.decode())
        assert sent["model"] == "llama3"
        assert sent["messages"][0]["role"] == "user"
        assert res.json()["choices"][0]["message"]["content"] == "hello"
        assert res.json()["usage"]["total_tokens"] == 7

    def test_ollama_unavailable_503(
        self, proxy_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:1")
        with respx.mock:
            respx.post(url__regex=r".*").mock(side_effect=httpx.ConnectError("nope"))
            res = proxy_client.post(
                "/v1/a2a/v1/messages",
                headers=_auth(),
                json=_anthropic_body("ollama:llama3"),
            )
        assert res.status_code == 503
        assert res.json()["error"] == "ollama_unavailable"


# ---------------------------------------------------------------------------
# Vertex
# ---------------------------------------------------------------------------


class TestVertexE2E:
    def test_missing_project_400(
        self, proxy_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("VERTEX_PROJECT", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
        monkeypatch.setenv("GOOGLE_OAUTH_ACCESS_TOKEN", "ya29.test")
        res = proxy_client.post(
            "/v1/a2a/v1/messages",
            headers=_auth(),
            json=_anthropic_body("vertex-gemini-2.0-flash"),
        )
        assert res.status_code == 400
        assert res.json()["error"] == "missing_vertex_project"

    def test_missing_credentials_401(
        self, proxy_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VERTEX_PROJECT", "proj")
        monkeypatch.delenv("GOOGLE_OAUTH_ACCESS_TOKEN", raising=False)
        # Force empty token (skip gcloud)
        monkeypatch.setattr(
            "evolver.proxy.router.vertex_route._get_access_token",
            lambda: "",
        )
        res = proxy_client.post(
            "/v1/a2a/v1/messages",
            headers=_auth(),
            json=_anthropic_body("vertex-gemini-2.0-flash"),
        )
        assert res.status_code == 401
        assert res.json()["error"] == "missing_vertex_credentials"

    @respx.mock
    def test_vertex_forward(
        self, proxy_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VERTEX_PROJECT", "proj-e2e")
        monkeypatch.setenv("VERTEX_LOCATION", "us-central1")
        monkeypatch.setenv("GOOGLE_OAUTH_ACCESS_TOKEN", "ya29.test")
        monkeypatch.setattr(
            "evolver.proxy.router.vertex_route._get_access_token",
            lambda: "ya29.test",
        )
        route = respx.post(url__regex=r"https://us-central1-aiplatform\.googleapis\.com/.*").mock(
            return_value=httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [{"text": "vertex-ok"}],
                            }
                        }
                    ]
                },
            )
        )
        res = proxy_client.post(
            "/v1/a2a/v1/messages",
            headers=_auth(),
            json=_anthropic_body("vertex-gemini-2.0-flash"),
        )
        assert res.status_code == 200, res.text
        assert route.called
        assert "Bearer ya29.test" in route.calls.last.request.headers.get("Authorization", "")
        assert res.json()["candidates"][0]["content"]["parts"][0]["text"] == "vertex-ok"


# ---------------------------------------------------------------------------
# OpenAI / responses route
# ---------------------------------------------------------------------------


class TestOpenAIE2E:
    def test_missing_key_401(
        self, proxy_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        res = proxy_client.post(
            "/v1/a2a/v1/messages",
            headers=_auth(),
            json=_anthropic_body("gpt-4o"),
        )
        assert res.status_code == 401
        assert res.json()["error"] == "missing_openai_api_key"

    @respx.mock
    def test_openai_chat_completions_transform(
        self, proxy_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com")
        route = respx.post("https://api.openai.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "chatcmpl-1",
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "world"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 3,
                        "completion_tokens": 1,
                        "total_tokens": 4,
                    },
                },
            )
        )
        res = proxy_client.post(
            "/v1/a2a/v1/messages",
            headers=_auth(),
            json={
                "model": "gpt-4o",
                "max_tokens": 32,
                "system": "be brief",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert res.status_code == 200, res.text
        assert route.called
        sent = json.loads(route.calls.last.request.content.decode())
        assert sent["model"] == "gpt-4o"
        assert sent["messages"][0] == {"role": "system", "content": "be brief"}
        assert sent["messages"][1]["content"] == "hello"
        assert res.json()["usage"]["total_tokens"] == 4

    @respx.mock
    def test_openai_4xx_passthrough_status(
        self, proxy_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com")
        respx.post(url__regex=r".*/v1/chat/completions").mock(
            return_value=httpx.Response(
                429, json={"error": {"message": "rate limited"}}
            )
        )
        res = proxy_client.post(
            "/v1/a2a/v1/messages",
            headers=_auth(),
            json=_anthropic_body("gpt-4o-mini"),
        )
        assert res.status_code == 429, res.text
        assert res.json()["error"] == "upstream_client_error"

    @respx.mock
    def test_o3_routes_openai(
        self, proxy_client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com")
        route = respx.post(url__regex=r".*/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={"id": "x", "choices": [{"message": {"content": "ok"}}]},
            )
        )
        res = proxy_client.post(
            "/v1/a2a/v1/messages",
            headers=_auth(),
            json=_anthropic_body("o3-mini"),
        )
        assert res.status_code == 200, res.text
        assert route.called


# ---------------------------------------------------------------------------
# Cross-cutting
# ---------------------------------------------------------------------------


class TestAuthAndErrors:
    def test_messages_require_auth(self, proxy_client: TestClient) -> None:
        res = proxy_client.post(
            "/v1/a2a/v1/messages",
            json=_anthropic_body("gpt-4o"),
        )
        assert res.status_code == 401

    def test_invalid_token(self, proxy_client: TestClient) -> None:
        res = proxy_client.post(
            "/v1/a2a/v1/messages",
            headers={"Authorization": "Bearer wrong"},
            json=_anthropic_body("gpt-4o"),
        )
        assert res.status_code == 401
