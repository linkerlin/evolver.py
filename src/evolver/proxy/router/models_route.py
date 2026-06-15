"""Models route — aggregate available models from all configured upstreams.

Equivalent to ``evolver/src/proxy/router/modelsRoute.js``.

Returns a unified ``/v1/models`` response listing models from Anthropic,
OpenAI, Gemini, Vertex, and Ollama (whichever are configured). The response
follows the OpenAI ``/v1/models`` schema so it works as a drop-in.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from fastapi.responses import JSONResponse

#: Static model catalog per upstream (avoids a live API call per request).
_STATIC_MODELS: dict[str, list[str]] = {
    "anthropic": [
        "claude-sonnet-4-20250514",
        "claude-3-7-sonnet-20250219",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
    ],
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "o3-mini",
        "o4-mini",
    ],
    "gemini": [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
    ],
    "vertex": [
        "gemini-2.0-flash",
        "gemini-1.5-pro",
    ],
}


def _get_ollama_models() -> list[str]:
    """Fetch model list from local Ollama (best-effort)."""
    try:
        import httpx

        url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        resp = httpx.get(f"{url}/api/tags", timeout=3.0)
        if resp.status_code == 200:
            data = resp.json()
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception:
        pass
    return []


def list_models() -> dict[str, Any]:
    """Return a unified model list in OpenAI ``/v1/models`` format."""
    models: list[dict[str, Any]] = []
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    # Determine which upstreams are configured.
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        for name in _STATIC_MODELS["anthropic"]:
            models.append({"id": name, "object": "model", "created": now, "owned_by": "anthropic"})

    if os.environ.get("OPENAI_API_KEY"):
        for name in _STATIC_MODELS["openai"]:
            models.append({"id": name, "object": "model", "created": now, "owned_by": "openai"})

    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        for name in _STATIC_MODELS["gemini"]:
            models.append({"id": name, "object": "model", "created": now, "owned_by": "google"})

    if os.environ.get("VERTEX_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT"):
        for name in _STATIC_MODELS["vertex"]:
            models.append({"id": name, "object": "model", "created": now, "owned_by": "vertex"})

    # Ollama models (dynamic).
    ollama_models = _get_ollama_models()
    for name in ollama_models:
        models.append({"id": name, "object": "model", "created": now, "owned_by": "ollama"})

    return {"object": "list", "data": models}


async def handle_models() -> JSONResponse:
    """Handle ``GET /v1/models``."""
    return JSONResponse(list_models())


__all__ = ["handle_models", "list_models"]
