"""Trace extractor — extract request/response metadata from proxy traffic.

Equivalent to ``evolver/src/proxy/trace/extractor.js``.

Extracts token usage, latency, model, user identity, thinking effort,
session ID, and error info from LLM proxy requests/responses.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from typing import Any

# ── helpers ─────────────────────────────────────────────────────────


def hash_trace_value(value: Any, prefix: str = "hash") -> str:
    """Stable short hash used for session / user / cwd redaction in traces.

    Mirrors Node ``hashTraceValue``: ``{prefix}:{sha256(utf8)[:16]}``.
    """
    text = str(value or "")
    if not text:
        return ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _clip_string(value: Any, max_len: int = 96) -> str:
    text = str(value or "").strip()
    return text[:max_len] if text else ""


def _get_header(headers: dict[str, Any], name: str) -> str:
    """Case-insensitive header lookup."""
    if not isinstance(headers, dict):
        return ""
    lower = name.lower()
    for k, v in headers.items():
        if str(k).lower() == lower:
            return str(v or "")
    return ""


def _is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _content_to_text(value: Any) -> str:
    """Flatten message content (string or array of blocks) to plain text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for block in value:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
        return " ".join(parts)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("content") or "")
    return str(value)


def _user_account_key_from_identity_field(value: Any) -> str:  # noqa: PLR0911
    """Extract a stable identity key from various user_id formats.

    Claude Code packs per-session identity into metadata.user_id as a
    JSON object/string carrying a device_id + session_id. We extract the
    device_id (stable per device) as the account key.
    """
    if not value:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        # Try to parse as JSON (Claude Code identity object)
        if text.startswith("{"):
            try:
                obj = json.loads(text)
                if isinstance(obj, dict):
                    # Prefer device_id (stable per device), fall back to session_id
                    did = obj.get("device_id") or ""
                    if isinstance(did, str) and did:
                        return did
                    sid = obj.get("session_id") or ""
                    if isinstance(sid, str) and sid:
                        return sid
            except (json.JSONDecodeError, TypeError):
                pass
        return text
    if isinstance(value, dict):
        did = value.get("device_id") or ""
        if isinstance(did, str) and did:
            return did
        sid = value.get("session_id") or ""
        if isinstance(sid, str) and sid:
            return sid
    return str(value) if value else ""


# ── token usage ─────────────────────────────────────────────────────


def extract_usage(response_body: dict[str, Any]) -> dict[str, int]:
    """Extract token usage counts from an LLM response body.

    Supports Anthropic, OpenAI, and Gemini response shapes.
    """
    usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

    resp_usage = response_body.get("usage")
    if isinstance(resp_usage, dict):
        input_t = resp_usage.get("input_tokens")
        output_t = resp_usage.get("output_tokens")
        if input_t is None:
            input_t = resp_usage.get("prompt_tokens", 0)
        if output_t is None:
            output_t = resp_usage.get("completion_tokens", 0)
        usage["input_tokens"] = int(input_t)
        usage["output_tokens"] = int(output_t)
        return usage

    meta = response_body.get("usageMetadata")
    if isinstance(meta, dict):
        usage["input_tokens"] = int(meta.get("promptTokenCount", 0))
        usage["output_tokens"] = int(meta.get("candidatesTokenCount", 0))

    return usage


# ── user identity ───────────────────────────────────────────────────


def extract_user_id_hash(
    headers: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> str:
    """Extract and hash user identity from request headers/body.

    Checks (in order):
      1. ``body.metadata.user_id``
      2. ``body.user``
      3. ``body.metadata.account_id``
      4. Header ``x-account-id``
      5. Header ``x-user-id``

    Returns ``user_id_sha256:{hash}`` or empty string.
    """
    headers = headers or {}
    body = body or {}

    identity = ""
    metadata = body.get("metadata")
    if isinstance(metadata, dict):
        identity = (
            _user_account_key_from_identity_field(metadata.get("user_id"))
            or _user_account_key_from_identity_field(metadata.get("account_id"))
        )
    if not identity:
        identity = _user_account_key_from_identity_field(body.get("user"))
    if not identity:
        for name in ("x-account-id", "x-user-id"):
            identity = _user_account_key_from_identity_field(_get_header(headers, name))
            if identity:
                break

    return hash_trace_value(identity, "user_id_sha256") if identity else ""


# ── session identity ────────────────────────────────────────────────


def extract_session_id(
    headers: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> str:
    """Extract a session identifier from headers/body.

    Checks headers ``x-session-id``, ``x-cursor-session-id``,
    ``x-conversation-id``; falls back to the ``session_id`` field inside
    Claude Code's ``metadata.user_id`` identity object.
    """
    headers = headers or {}
    body = body or {}

    for name in ("x-session-id", "x-cursor-session-id", "x-conversation-id"):
        sid = _clip_string(_get_header(headers, name), 96)
        if sid:
            return sid

    metadata = body.get("metadata")
    if isinstance(metadata, dict):
        raw_uid = metadata.get("user_id")
        if isinstance(raw_uid, str) and raw_uid.strip().startswith("{"):
            try:
                obj = json.loads(raw_uid)
                if isinstance(obj, dict):
                    sid_val: Any = obj.get("session_id")
                    if isinstance(sid_val, str) and sid_val:
                        return _clip_string(sid_val, 96)
            except (json.JSONDecodeError, TypeError):
                pass

    return ""


# ── thinking effort ─────────────────────────────────────────────────


def _pick_effort(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if _is_finite_number(value):
        return str(int(float(value))) if float(value) == int(float(value)) else str(float(value))
    return ""


def extract_thinking_effort(body: dict[str, Any] | None = None) -> str:  # noqa: PLR0911, PLR0912
    """Extract thinking/reasoning effort from a request body.

    Supports OpenAI reasoning_effort, Anthropic thinking config,
    output_config, Gemini thinkingConfig, and metadata fallback.
    """
    if not isinstance(body, dict):
        return ""

    # OpenAI reasoning effort (object or flat field).
    reasoning = body.get("reasoning")
    reasoning_obj = reasoning if isinstance(reasoning, dict) else None
    openai_effort = _pick_effort(
        reasoning_obj.get("effort") if reasoning_obj else None
    ) or _pick_effort(body.get("reasoning_effort"))
    if openai_effort:
        return _clip_string(openai_effort, 32)

    # Anthropic thinking config.
    thinking = body.get("thinking")
    if isinstance(thinking, dict):
        bt = thinking.get("budget_tokens")
        if _is_finite_number(bt) and bt is not None:
            return _clip_string(f"budget:{int(float(bt))}", 32)
        t = _pick_effort(thinking.get("type"))
        if t:
            return _clip_string(t, 32)
    else:
        tt = _pick_effort(thinking)
        if tt:
            return _clip_string(tt, 32)

    # output_config.effort (some Anthropic/Bedrock variants).
    output_config = body.get("output_config")
    if isinstance(output_config, dict):
        oe = _pick_effort(output_config.get("effort"))
        if oe:
            return _clip_string(oe, 32)

    # Gemini thinkingConfig (budget / level).
    gen_config = body.get("generationConfig")
    if isinstance(gen_config, dict):
        tc = gen_config.get("thinkingConfig")
        if isinstance(tc, dict):
            tb = tc.get("thinkingBudget")
            if _is_finite_number(tb) and tb is not None:
                return _clip_string(f"budget:{int(float(tb))}", 32)
            level = _pick_effort(tc.get("reasoningEffort") or tc.get("effort"))
            if level:
                return _clip_string(level, 32)

    # metadata fallback.
    metadata = body.get("metadata")
    if isinstance(metadata, dict):
        me = _pick_effort(metadata.get("thinking_effort") or metadata.get("reasoning_effort"))
        if me:
            return _clip_string(me, 32)

    return ""


# ── trace entry builder ─────────────────────────────────────────────

_CWD_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"workspace\s*path[:=]\s*([A-Za-z]:[\\/][^\s\"'\n\r]+|/[^\s\"'\n\r]+)",
        re.I,
    ),
    re.compile(
        r"(?:current|primary)\s+working\s+directory(?:\s+is)?[:=]?\s*"
        r"([A-Za-z]:[\\/][^\s\"'\n\r]+|/[^\s\"'\n\r]+)",
        re.I,
    ),
    re.compile(
        r"working\s+directory[:=]\s*([A-Za-z]:[\\/][^\s\"'\n\r]+|/[^\s\"'\n\r]+)",
        re.I,
    ),
    re.compile(r"\bcwd[:=]\s*([A-Za-z]:[\\/][^\s\"'\n\r]+|/[^\s\"'\n\r]+)", re.I),
]


def extract_cwd(body: dict[str, Any] | None = None) -> str:
    """Extract the working directory path from request body fields.

    Searches instructions, system, input, and system/user/developer
    messages for path-like patterns.
    """
    if not isinstance(body, dict):
        return ""

    candidates: list[str] = []
    candidates.append(_content_to_text(body.get("instructions")))
    candidates.append(_content_to_text(body.get("system")))
    candidates.append(_content_to_text(body.get("input")))

    messages = body.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role in ("system", "user", "developer"):
                candidates.append(_content_to_text(msg.get("content")))

    for text in candidates:
        if not text:
            continue
        for pattern in _CWD_PATTERNS:
            m = pattern.search(text)
            if m:
                return m.group(1)

    return ""


def extract_trace_entry(
    request_body: dict[str, Any],
    response_body: dict[str, Any] | None,
    *,
    status_code: int = 200,
    elapsed_ms: float = 0.0,
    upstream: str = "",
    headers: dict[str, Any] | None = None,
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

    # Enriched metadata
    uid = extract_user_id_hash(headers, request_body)
    if uid:
        entry["user_id_hash"] = uid
    sid = extract_session_id(headers, request_body)
    if sid:
        entry["session_id"] = sid
    effort = extract_thinking_effort(request_body)
    if effort:
        entry["thinking_effort"] = effort
    cwd = extract_cwd(request_body)
    if cwd:
        entry["cwd_hash"] = hash_trace_value(cwd)

    if response_body and isinstance(response_body, dict):
        entry["usage"] = extract_usage(response_body)
        if "error" in response_body:
            entry["error"] = str(response_body["error"])[:200]
    return entry


__all__ = [
    "extract_cwd",
    "extract_session_id",
    "extract_thinking_effort",
    "extract_trace_entry",
    "extract_usage",
    "extract_user_id_hash",
    "hash_trace_value",
]
