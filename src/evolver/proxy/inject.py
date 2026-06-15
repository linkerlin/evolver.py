"""Context injector — inject proxy-side context into request/response payloads.

Equivalent to ``evolver/src/proxy/inject.js``.

Provides hooks to add metadata (trace IDs, feature flags, usage hints) to
outgoing LLM requests and to post-process responses before returning them
to the client. Used by the proxy middleware layer.
"""

from __future__ import annotations

import uuid
from typing import Any


def inject_trace_id(body: dict[str, Any]) -> dict[str, Any]:
    """Add a ``_evolver_trace_id`` to the request body for diagnostics."""
    body.setdefault("metadata", {})
    if isinstance(body["metadata"], dict):
        body["metadata"]["_evolver_trace_id"] = str(uuid.uuid4())
    return body


def inject_feature_hints(
    body: dict[str, Any], hints: dict[str, Any]
) -> dict[str, Any]:
    """Inject feature-routing hints into the request body."""
    if hints:
        body.setdefault("metadata", {})
        if isinstance(body["metadata"], dict):
            body["metadata"]["_evolver_hints"] = hints
    return body


def strip_internal_fields(body: dict[str, Any]) -> dict[str, Any]:
    """Remove ``_evolver_*`` internal fields before sending upstream."""
    if isinstance(body.get("metadata"), dict):
        meta = body["metadata"]
        for key in list(meta.keys()):
            if key.startswith("_evolver_"):
                del meta[key]
        if not meta:
            del body["metadata"]
    return body


def post_process_response(
    response_body: dict[str, Any], trace_id: str = ""
) -> dict[str, Any]:
    """Add internal metadata to the response before returning to client."""
    if trace_id:
        response_body.setdefault("_evolver", {})
        if isinstance(response_body["_evolver"], dict):
            response_body["_evolver"]["trace_id"] = trace_id
    return response_body


__all__ = [
    "inject_feature_hints",
    "inject_trace_id",
    "post_process_response",
    "strip_internal_fields",
]
