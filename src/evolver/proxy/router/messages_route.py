"""LLM message router: proxy /v1/messages to Anthropic or AWS Bedrock.

Equivalent to evolver/src/proxy/router/messagesRoute.js.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from evolver.gep.assets import BEDROCK_MODEL_MAP, canonicalize_for_bedrock
from evolver.proxy.router.cache_passthrough import get_cached, set_cache
from evolver.proxy.router.model_router import select_upstream_for_model

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_DEFAULT_TIMEOUT = 60.0
BEDROCK_DEFAULT_TIMEOUT = 90.0


def _build_anthropic_headers() -> dict[str, str]:
    api_key = os.environ.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_AUTH_TOKEN", ""))
    return {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }


def _anthropic_body_transform(body: dict[str, Any]) -> dict[str, Any]:
    """Prepare body for Anthropic API."""
    # Anthropic accepts the body mostly as-is; just ensure max_tokens is present
    transformed = dict(body)
    if "max_tokens" not in transformed:
        transformed["max_tokens"] = 4096
    return transformed


def _bedrock_body_transform(body: dict[str, Any]) -> dict[str, Any]:
    """Prepare body for Bedrock InvokeModel API.

    - Remove 'stream' field (Bedrock handles streaming differently)
    - Handle 'thinking' type adaptive → enabled/disabled
    - Set max_tokens
    """
    transformed: dict[str, Any] = {}

    messages = body.get("messages", [])
    system = body.get("system", "")
    model = body.get("model", "")

    transformed["messages"] = messages
    if system:
        transformed["system"] = system

    # Handle thinking / adaptive thinking
    thinking = body.get("thinking")
    if isinstance(thinking, dict):
        if thinking.get("type") == "adaptive":
            # Bedrock does not support 'adaptive'; downgrade to 'enabled' or 'disabled'
            budget = thinking.get("budget_tokens", 0)
            transformed["thinking"] = {
                "type": "enabled" if budget > 0 else "disabled",
                "budget_tokens": budget,
            }
        else:
            transformed["thinking"] = thinking

    max_tokens = body.get("max_tokens", 4096)
    transformed["max_tokens"] = max_tokens

    # Add modelId for Bedrock context
    transformed["modelId"] = canonicalize_for_bedrock(model)

    return transformed


async def _proxy_anthropic_stream(
    headers: dict[str, str],
    transformed: dict[str, Any],
) -> StreamingResponse | JSONResponse:
    """Passthrough Anthropic SSE stream to the client."""
    import httpx

    if not headers.get("x-api-key"):
        return JSONResponse({"error": "missing_api_key"}, status_code=401)

    async def event_stream() -> AsyncIterator[bytes]:
        try:
            async with httpx.AsyncClient(timeout=ANTHROPIC_DEFAULT_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    ANTHROPIC_API_URL,
                    headers=headers,
                    json=transformed,
                ) as response:
                    if response.status_code >= 500:
                        detail = (await response.aread()).decode("utf-8", errors="replace")[:500]
                        payload = {"error": "upstream_error", "detail": detail}
                        yield f"data: {json.dumps(payload)}\n\n".encode()
                        return
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", errors="replace")[:500]
                        payload = {"error": "upstream_client_error", "detail": detail}
                        yield f"data: {json.dumps(payload)}\n\n".encode()
                        return
                    async for chunk in response.aiter_bytes():
                        yield chunk
        except httpx.TimeoutException:
            yield f"data: {json.dumps({'error': 'upstream_timeout'})}\n\n".encode()
        except Exception as exc:
            payload = {"error": "proxy_error", "detail": str(exc)}
            yield f"data: {json.dumps(payload)}\n\n".encode()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


async def proxy_anthropic(
    request: Request, body: dict[str, Any]
) -> JSONResponse | StreamingResponse:
    """Proxy request to Anthropic API."""
    import httpx

    headers = _build_anthropic_headers()
    transformed = _anthropic_body_transform(body)

    if body.get("stream"):
        return await _proxy_anthropic_stream(headers, transformed)

    # Check cache first (non-streaming only)
    cached = get_cached(body)
    if cached is not None:
        return JSONResponse(cached)

    try:
        async with httpx.AsyncClient(timeout=ANTHROPIC_DEFAULT_TIMEOUT) as client:
            response = await client.post(
                ANTHROPIC_API_URL,
                headers=headers,
                json=transformed,
            )

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

        data = response.json()
        set_cache(body, data)
        return JSONResponse(data)
    except httpx.TimeoutException:
        return JSONResponse(
            {"error": "upstream_timeout"},
            status_code=504,
        )
    except Exception as exc:
        return JSONResponse(
            {"error": "proxy_error", "detail": str(exc)},
            status_code=502,
        )


def _bedrock_stream_event_bytes(event: dict[str, Any]) -> bytes | None:
    chunk = event.get("chunk")
    if not isinstance(chunk, dict):
        return None
    payload = chunk.get("bytes", b"")
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if not payload:
        return None
    text = payload.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    return f"data: {text}\n\n".encode()


async def _proxy_bedrock_stream(model_id: str, transformed: dict[str, Any]) -> StreamingResponse:
    """Stream Bedrock invoke_model_with_response_stream as SSE."""
    import boto3

    region = os.environ.get("AWS_REGION", "us-east-1")

    async def event_stream() -> AsyncIterator[bytes]:
        try:
            client = boto3.client("bedrock-runtime", region_name=region)
            response = client.invoke_model_with_response_stream(
                modelId=model_id,
                body=json.dumps(transformed),
                contentType="application/json",
                accept="application/json",
            )
            for event in response.get("body", []):
                chunk = _bedrock_stream_event_bytes(event)
                if chunk is not None:
                    yield chunk
        except Exception as exc:
            payload = {"error": "bedrock_error", "detail": str(exc)}
            yield f"data: {json.dumps(payload)}\n\n".encode()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


async def proxy_bedrock(request: Request, body: dict[str, Any]) -> JSONResponse | StreamingResponse:
    """Proxy request to AWS Bedrock InvokeModel API."""
    try:
        import boto3
    except ImportError:
        return JSONResponse(
            {"error": "bedrock_unavailable", "detail": "boto3 not installed"},
            status_code=503,
        )

    transformed = _bedrock_body_transform(body)
    model_id = transformed.pop("modelId", canonicalize_for_bedrock(body.get("model", "")))

    if body.get("stream"):
        return await _proxy_bedrock_stream(model_id, transformed)

    try:
        import boto3

        client = boto3.client(
            "bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1")
        )
        response = client.invoke_model(
            modelId=model_id,
            body=json.dumps(transformed),
            contentType="application/json",
            accept="application/json",
        )
        data = json.loads(response["body"].read().decode("utf-8"))
        set_cache(body, data)
        return JSONResponse(data)
    except Exception as exc:
        return JSONResponse(
            {"error": "bedrock_error", "detail": str(exc)},
            status_code=502,
        )


async def handle_messages(
    request: Request, body: dict[str, Any]
) -> JSONResponse | StreamingResponse:
    """Route /v1/messages to the appropriate upstream (format-aware)."""
    model = str(body.get("model") or "")
    lower = model.lower()

    # Route by raw model id first (prefixes matter), then normalise body.model.
    if lower.startswith("ollama:"):
        upstream = "ollama"
        body = {**body, "model": model.split(":", 1)[1] or "llama3"}
    elif lower.startswith("vertex-"):
        upstream = "vertex"
        body = {**body, "model": model[len("vertex-") :]}
    else:
        upstream = select_upstream_for_model(model)

    if upstream == "bedrock":
        return await proxy_bedrock(request, body)
    if upstream == "gemini":
        from evolver.proxy.router.gemini_route import proxy_gemini

        return await proxy_gemini(request, body)
    if upstream == "vertex":
        from evolver.proxy.router.vertex_route import proxy_vertex

        return await proxy_vertex(request, body)
    if upstream == "ollama":
        from evolver.proxy.router.ollama_route import proxy_ollama

        return await proxy_ollama(request, body)
    if upstream == "openai":
        from evolver.proxy.router.responses_route import proxy_openai

        return await proxy_openai(request, body)
    return await proxy_anthropic(request, body)


__all__ = [
    "BEDROCK_MODEL_MAP",
    "_bedrock_stream_event_bytes",
    "_proxy_anthropic_stream",
    "_proxy_bedrock_stream",
    "canonicalize_for_bedrock",
    "handle_messages",
    "proxy_anthropic",
    "proxy_bedrock",
]
