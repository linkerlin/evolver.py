"""Gemini route — proxy /v1/messages to Google Gemini API.

Equivalent to ``evolver/src/proxy/router/geminiRoute.js``.

Transforms Anthropic-style message requests to Google's Generative Language
API format (``generativelanguage.googleapis.com``), with SSE streaming
support. Activated when the model name starts with ``gemini-``.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_TIMEOUT = 60.0


def _build_gemini_headers() -> dict[str, str]:
    api_key = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", ""))
    return {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }


def _transform_to_gemini(body: dict[str, Any]) -> dict[str, Any]:
    """Transform Anthropic-style body to Gemini generateContent format."""
    messages = body.get("messages", [])
    system = body.get("system", "")
    model = body.get("model", "gemini-2.0-flash")

    contents: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        # Flatten content blocks to text.
        if isinstance(content, list):
            text_parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            content = " ".join(text_parts)
        gemini_role = "user" if role == "user" else "model"
        contents.append({"role": gemini_role, "parts": [{"text": str(content)}]})

    payload: dict[str, Any] = {"contents": contents}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": str(system)}]}

    # Generation config.
    gen_config: dict[str, Any] = {}
    if body.get("max_tokens"):
        gen_config["maxOutputTokens"] = body["max_tokens"]
    if body.get("temperature") is not None:
        gen_config["temperature"] = body["temperature"]
    if body.get("top_p") is not None:
        gen_config["topP"] = body["top_p"]
    if gen_config:
        payload["generationConfig"] = gen_config

    payload["_model"] = model  # stripped before sending
    return payload


async def proxy_gemini(request: Request, body: dict[str, Any]) -> JSONResponse | StreamingResponse:
    """Proxy request to Google Gemini API."""
    import httpx

    headers = _build_gemini_headers()
    if not headers.get("x-goog-api-key"):
        return JSONResponse({"error": "missing_gemini_api_key"}, status_code=401)

    transformed = _transform_to_gemini(body)
    model = transformed.pop("_model", "gemini-2.0-flash")
    stream = body.get("stream", False)
    method = "streamGenerateContent" if stream else "generateContent"
    url = f"{GEMINI_BASE_URL}/models/{model}:{method}"
    if stream:
        url += "?alt=sse"

    try:
        if stream:
            return await _proxy_gemini_stream(url, headers, transformed)
        async with httpx.AsyncClient(timeout=GEMINI_TIMEOUT) as client:
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


async def _proxy_gemini_stream(
    url: str, headers: dict[str, str], body: dict[str, Any]
) -> StreamingResponse:
    import httpx

    async def event_stream() -> AsyncIterator[bytes]:
        try:
            async with httpx.AsyncClient(timeout=GEMINI_TIMEOUT) as client:
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


async def proxy_gemini_native(
    request: Request,
    model_action: str,
    body: dict[str, Any],
) -> JSONResponse | StreamingResponse:
    """Native Gemini passthrough: ``/v1beta/models/{model}:{action}``.

    No Anthropic↔Gemini translation — body is forwarded as-is (Node E2E contract).
    *model_action* is a single path segment like ``gemini-2.0-flash:generateContent``.
    """
    import httpx

    headers = _build_gemini_headers()
    # Prefer client-supplied goog key when present (SDK style).
    client_key = request.headers.get("x-goog-api-key")
    if client_key:
        headers["x-goog-api-key"] = client_key
    if not headers.get("x-goog-api-key"):
        return JSONResponse({"error": "missing_gemini_api_key"}, status_code=401)

    # model_action may include query already stripped by FastAPI; stream via action name.
    is_stream = "streamGenerateContent" in model_action
    url = f"{GEMINI_BASE_URL}/models/{model_action}"
    # Preserve alt=sse when client requested it.
    qs = str(request.url.query or "")
    if qs:
        url = f"{url}?{qs}"
    elif is_stream and "alt=" not in model_action:
        # Default stream to SSE when not specified (matches common SDK usage).
        pass

    try:
        if is_stream and "alt=sse" in url:
            return await _proxy_gemini_stream(url, headers, body)
        async with httpx.AsyncClient(timeout=GEMINI_TIMEOUT) as client:
            response = await client.post(url, headers=headers, json=body)
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
        # Byte-faithful JSON passthrough.
        return JSONResponse(response.json(), status_code=response.status_code)
    except httpx.TimeoutException:
        return JSONResponse({"error": "upstream_timeout"}, status_code=504)
    except Exception as exc:
        return JSONResponse({"error": "proxy_error", "detail": str(exc)}, status_code=502)


__all__ = ["proxy_gemini", "proxy_gemini_native"]
