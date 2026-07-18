"""OpenAI Responses route — proxy to OpenAI-compatible APIs.

Equivalent to ``evolver/src/proxy/router/responsesRoute.js``.

Transforms Anthropic-style message requests to OpenAI chat completions
format and forwards to ``OPENAI_BASE_URL`` (default: ``api.openai.com``).
Supports SSE streaming. Activated when the model name starts with ``gpt-``
or ``o1-``/``o3-``/``o4-``.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

OPENAI_DEFAULT_URL = "https://api.openai.com"
OPENAI_TIMEOUT = 60.0


def _get_openai_url() -> str:
    return os.environ.get("OPENAI_BASE_URL", OPENAI_DEFAULT_URL).rstrip("/")


def _build_openai_headers() -> dict[str, str]:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }


def _transform_to_openai(body: dict[str, Any]) -> dict[str, Any]:
    """Transform Anthropic-style body to OpenAI chat completions format."""
    messages = body.get("messages", [])
    system = body.get("system", "")
    model = body.get("model", "gpt-4o")

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


async def proxy_openai(request: Request, body: dict[str, Any]) -> JSONResponse | StreamingResponse:
    """Proxy request to OpenAI-compatible API."""
    import httpx

    headers = _build_openai_headers()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return JSONResponse({"error": "missing_openai_api_key"}, status_code=401)

    transformed = _transform_to_openai(body)
    stream = body.get("stream", False)
    url = f"{_get_openai_url()}/v1/chat/completions"

    try:
        if stream:
            return await _proxy_openai_stream(url, headers, transformed)
        async with httpx.AsyncClient(timeout=OPENAI_TIMEOUT) as client:
            response = await client.post(url, headers=headers, json=transformed)
        if response.status_code >= 500:
            return JSONResponse(
                {"error": "upstream_error", "detail": response.text[:500]},
                status_code=502,
                headers={"Retry-After": "10"},
            )
        if response.status_code >= 400:
            return JSONResponse(
                {"error": "upstream_client_error", "detail": response.text[:500]},
                status_code=response.status_code,
            )
        return JSONResponse(response.json())
    except httpx.TimeoutException:
        return JSONResponse({"error": "upstream_timeout"}, status_code=504)
    except Exception as exc:
        return JSONResponse({"error": "proxy_error", "detail": str(exc)}, status_code=502)


async def _proxy_openai_stream(
    url: str, headers: dict[str, str], body: dict[str, Any]
) -> StreamingResponse:
    import httpx

    async def event_stream() -> AsyncIterator[bytes]:
        try:
            async with httpx.AsyncClient(timeout=OPENAI_TIMEOUT) as client:
                async with client.stream("POST", url, headers=headers, json=body) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", errors="replace")[:500]
                        yield f"data: {json.dumps({'error': 'upstream_error', 'detail': detail})}\n\n".encode()
                        return
                    async for chunk in response.aiter_bytes():
                        yield chunk
        except httpx.TimeoutException:
            yield f"data: {json.dumps({'error': 'upstream_timeout'})}\n\n".encode()
        except Exception as exc:
            yield f"data: {json.dumps({'error': 'proxy_error', 'detail': str(exc)})}\n\n".encode()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


__all__ = ["proxy_openai"]
