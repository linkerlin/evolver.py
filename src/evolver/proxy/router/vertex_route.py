"""Vertex AI route — proxy /v1/messages to Google Vertex AI.

Equivalent to ``evolver/src/proxy/router/vertexRoute.js``.

Routes to ``{REGION}-aiplatform.googleapis.com`` using the Gemini model
family on Vertex. Requires ``GOOGLE_CLOUD_PROJECT`` and
``GOOGLE_CLOUD_LOCATION`` (or ``VERTEX_PROJECT`` / ``VERTEX_LOCATION``).
Authentication uses Google Cloud default credentials (ADC).
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from evolver.proxy.router.gemini_route import _transform_to_gemini

VERTEX_TIMEOUT = 90.0


def _vertex_endpoint(model: str, stream: bool) -> str:
    project = os.environ.get("VERTEX_PROJECT", os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    location = os.environ.get("VERTEX_LOCATION", os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    method = "streamGenerateContent" if stream else "generateContent"
    base = f"https://{location}-aiplatform.googleapis.com/v1"
    return (
        f"{base}/projects/{project}/locations/{location}"
        f"/publishers/google/models/{model}:{method}"
    )


def _get_access_token() -> str:
    """Get Google Cloud access token via ADC."""
    try:
        import subprocess

        result = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN", "")


async def proxy_vertex(
    request: Request, body: dict[str, Any]
) -> JSONResponse | StreamingResponse:
    """Proxy request to Google Vertex AI."""
    import httpx

    token = _get_access_token()
    if not token:
        return JSONResponse(
            {"error": "missing_vertex_credentials", "detail": "No ADC token or GOOGLE_OAUTH_ACCESS_TOKEN"},
            status_code=401,
        )

    project = os.environ.get("VERTEX_PROJECT", os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    if not project:
        return JSONResponse(
            {"error": "missing_vertex_project", "detail": "Set VERTEX_PROJECT or GOOGLE_CLOUD_PROJECT"},
            status_code=400,
        )

    transformed = _transform_to_gemini(body)
    model = transformed.pop("_model", "gemini-2.0-flash")
    stream = body.get("stream", False)
    url = _vertex_endpoint(model, stream)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if stream:
        url += "?alt=sse"

    try:
        if stream:
            return await _proxy_vertex_stream(url, headers, transformed)
        async with httpx.AsyncClient(timeout=VERTEX_TIMEOUT) as client:
            response = await client.post(url, headers=headers, json=transformed)
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
    except httpx.TimeoutException:
        return JSONResponse({"error": "upstream_timeout"}, status_code=504)
    except Exception as exc:
        return JSONResponse({"error": "proxy_error", "detail": str(exc)}, status_code=502)


async def _proxy_vertex_stream(
    url: str, headers: dict[str, str], body: dict[str, Any]
) -> StreamingResponse:
    import httpx

    async def event_stream() -> AsyncIterator[bytes]:
        try:
            async with httpx.AsyncClient(timeout=VERTEX_TIMEOUT) as client:
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


__all__ = ["proxy_vertex"]
