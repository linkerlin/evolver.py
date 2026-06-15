"""Trace extractor — extract request/response metadata from proxy traffic.

Equivalent to ``evolver/src/proxy/trace/extractor.js``.

Extracts token usage, latency, model, and error info from LLM proxy
requests/responses for diagnostics and Hub forwarding.
"""

from __future__ import annotations

import time
from typing import Any


def extract_usage(response_body: dict[str, Any]) -> dict[str, int]:
    """Extract token usage counts from an LLM response body.

    Supports Anthropic, OpenAI, and Gemini response shapes.
    """
    usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

    # Anthropic shape.
    resp_usage = response_body.get("usage")
    if isinstance(resp_usage, dict):
        usage["input_tokens"] = int(resp_usage.get("input_tokens", 0))
        usage["output_tokens"] = int(resp_usage.get("output_tokens", 0))
        return usage

    # OpenAI shape.
    if isinstance(resp_usage, dict):
        usage["input_tokens"] = int(resp_usage.get("prompt_tokens", usage["input_tokens"]))
        usage["output_tokens"] = int(resp_usage.get("completion_tokens", usage["output_tokens"]))
        return usage

    # Gemini shape (usageMetadata).
    meta = response_body.get("usageMetadata")
    if isinstance(meta, dict):
        usage["input_tokens"] = int(meta.get("promptTokenCount", 0))
        usage["output_tokens"] = int(meta.get("candidatesTokenCount", 0))

    return usage


def extract_trace_entry(
    request_body: dict[str, Any],
    response_body: dict[str, Any] | None,
    *,
    status_code: int = 200,
    elapsed_ms: float = 0.0,
    upstream: str = "",
) -> dict[str, Any]:
    """Build a trace entry from a proxy request/response pair."""
    model = request_body.get("model", "")
    entry: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": model,
        "upstream": upstream,
        "status_code": status_code,
        "elapsed_ms": round(elapsed_ms, 1),
    }
    if response_body and isinstance(response_body, dict):
        entry["usage"] = extract_usage(response_body)
        if "error" in response_body:
            entry["error"] = str(response_body["error"])[:200]
    return entry


__all__ = ["extract_trace_entry", "extract_usage"]
