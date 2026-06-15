"""Ollama route — proxy /v1/messages to a local Ollama instance.

Equivalent to ``evolver/src/proxy/router/ollamaRoute.js``.

Ollama runs on ``localhost:11434`` and exposes an OpenAI-compatible
``/v1/chat/completions`` endpoint. This route transforms Anthropic-style
messages to OpenAI chat format and forwards them. No auth needed.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

OLLAMA_DEFAULT_URL = "http://localhost:11434"
OLLAMA_TIMEOUT = 120.0


def _get_ollama_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", OLLAMA_DEFAULT_URL).rstrip("/")


def _transform_to_openai(body: dict[str, Any]) -> dict[str, Any]:
    """Transform Anthropic-style body to OpenAI chat completions format."""
    messages = body.get("messages", [])
    system = body.get("system", "")
    model = body.get("model", "llama3")

    openai_messages: list[dict[str, Any]] = []
    if system:
        openai_messages.append({"role": "system", "content": str(system)})
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            content = " ".join(text_parts)
        openai_messages.append({"role": role, "content": str(content)})

    payload: dict[str, Any] = {
        "model": model,
        "messages": openai_messages,
    }
    if body.get("max_tokens"):
        payload["max_tokens"] = body["max_tokens"]
    if body.get("temperature") is not None:
        payload["temperature"] = body["temperature"]
    if body.get("top_p") is not None:
        payload["top_p"] = body["top_p"]
    if body.get("stream"):
        payload["stream"] = True
    return payload


async def proxy_ollama(
    request: Request, body: dict[str, Any]
) -> JSONResponse | StreamingResponse:
    """Proxy request to local Ollama instance."""
    import httpx

    transformed = _transform_to_openai(body)
    stream = body.get("stream", False)
    url = f"{_get_ollama_url()}/v1/chat/completions"

    try:
        if stream:
            return await _proxy_ollama_stream(url, transformed)
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
            response = await client.post(url, json=transformed)
        if response.status_code >= 500:
            return JSONResponse(
                {"error": "upstream_error", "detail": response.text[:500]},
                status_code=502,
            )
        if response.status_code >= 400:
            return JSONResponse(
                {"error": "upstream_client_error", "detail": response.text[:500]},
                status_code=response.status_code,
            )
        return JSONResponse(response.json())
    except httpx.ConnectError:
        return JSONResponse(
            {"error": "ollama_unavailable", "detail": f"Cannot connect to {_get_ollama_url()}"},
            status_code=503,
        )
    except httpx.TimeoutException:
        return JSONResponse({"error": "upstream_timeout"}, status_code=504)
    except Exception as exc:
        return JSONResponse({"error": "proxy_error", "detail": str(exc)}, status_code=502)


async def _proxy_ollama_stream(
    url: str, body: dict[str, Any]
) -> StreamingResponse:
    import httpx

    async def event_stream() -> AsyncIterator[bytes]:
        try:
            async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
                async with client.stream("POST", url, json=body) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", errors="replace")[:500]
                        yield f"data: {json.dumps({'error': 'upstream_error', 'detail': detail})}\n\n".encode()
                        return
                    async for chunk in response.aiter_bytes():
                        yield chunk
        except httpx.ConnectError:
            yield f"data: {json.dumps({'error': 'ollama_unavailable'})}\n\n".encode()
        except httpx.TimeoutException:
            yield f"data: {json.dumps({'error': 'upstream_timeout'})}\n\n".encode()
        except Exception as exc:
            yield f"data: {json.dumps({'error': 'proxy_error', 'detail': str(exc)})}\n\n".encode()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


__all__ = ["proxy_ollama"]
