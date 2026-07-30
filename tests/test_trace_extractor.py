"""Tests for proxy trace extractor — user ID hash, thinking effort, session ID.

Equivalent to evolver/test/traceUserIdHash.test.js (9),
traceThinkingEffort.test.js (8), and traceUsage.test.js (7).
"""

from __future__ import annotations

from evolver.proxy.trace.extractor import (
    extract_cwd,
    extract_session_id,
    extract_thinking_effort,
    extract_trace_entry,
    extract_usage,
    extract_user_id_hash,
    hash_trace_value,
)


# ── hash_trace_value ────────────────────────────────────────────────


class TestHashTraceValue:
    def test_basic(self) -> None:
        h = hash_trace_value("abc", "prefix")
        assert h.startswith("prefix:")
        assert len(h) > len("prefix:")

    def test_empty(self) -> None:
        assert hash_trace_value("") == ""
        assert hash_trace_value(None) == ""

    def test_deterministic(self) -> None:
        assert hash_trace_value("x") == hash_trace_value("x")


# ── extract_user_id_hash ────────────────────────────────────────────


class TestExtractUserIdHash:
    def test_from_metadata_user_id_string(self) -> None:
        h = extract_user_id_hash({}, {"metadata": {"user_id": "user123"}})
        assert h.startswith("user_id_sha256:")

    def test_from_body_user(self) -> None:
        h = extract_user_id_hash({}, {"user": "alice@example.com"})
        assert h.startswith("user_id_sha256:")

    def test_from_metadata_account_id(self) -> None:
        h = extract_user_id_hash({}, {"metadata": {"account_id": "acct_456"}})
        assert h.startswith("user_id_sha256:")

    def test_from_header_x_account_id(self) -> None:
        h = extract_user_id_hash({"x-account-id": "acc789"}, {})
        assert h.startswith("user_id_sha256:")

    def test_from_header_x_user_id(self) -> None:
        h = extract_user_id_hash({"X-User-Id": "usr999"}, {})
        assert h.startswith("user_id_sha256:")

    def test_empty_returns_empty(self) -> None:
        assert extract_user_id_hash({}, {}) == ""

    def test_claude_code_json_identity(self) -> None:
        uid = '{"device_id": "dev_abc", "session_id": "sess_xyz"}'
        h = extract_user_id_hash({}, {"metadata": {"user_id": uid}})
        assert h.startswith("user_id_sha256:")
        # Should use device_id as the identity key
        expected = hash_trace_value("dev_abc", "user_id_sha256")
        assert h == expected

    def test_claude_code_dict_identity(self) -> None:
        h = extract_user_id_hash(
            {}, {"metadata": {"user_id": {"device_id": "dev_d", "session_id": "s_e"}}}
        )
        assert h == hash_trace_value("dev_d", "user_id_sha256")

    def test_case_insensitive_headers(self) -> None:
        h1 = extract_user_id_hash({"X-ACCOUNT-ID": "acc"}, {})
        h2 = extract_user_id_hash({"x-account-id": "acc"}, {})
        assert h1 == h2


# ── extract_session_id ──────────────────────────────────────────────


class TestExtractSessionId:
    def test_from_x_session_id(self) -> None:
        assert extract_session_id({"x-session-id": "sess123"}, {}) == "sess123"

    def test_from_x_cursor_session_id(self) -> None:
        assert extract_session_id({"x-cursor-session-id": "cur456"}, {}) == "cur456"

    def test_from_x_conversation_id(self) -> None:
        assert extract_session_id({"x-conversation-id": "conv789"}, {}) == "conv789"

    def test_empty(self) -> None:
        assert extract_session_id({}, {}) == ""

    def test_from_claude_code_identity(self) -> None:
        uid = '{"device_id": "d", "session_id": "from_metadata"}'
        assert extract_session_id({}, {"metadata": {"user_id": uid}}) == "from_metadata"

    def test_clipped(self) -> None:
        long_sid = "x" * 200
        assert len(extract_session_id({"x-session-id": long_sid}, {})) == 96


# ── extract_thinking_effort ─────────────────────────────────────────


class TestExtractThinkingEffort:
    def test_openai_reasoning_effort(self) -> None:
        assert extract_thinking_effort({"reasoning_effort": "high"}) == "high"

    def test_openai_reasoning_object(self) -> None:
        assert extract_thinking_effort({"reasoning": {"effort": "medium"}}) == "medium"

    def test_anthropic_thinking_budget(self) -> None:
        result = extract_thinking_effort({"thinking": {"budget_tokens": 10000}})
        assert result == "budget:10000"

    def test_anthropic_thinking_type(self) -> None:
        assert extract_thinking_effort({"thinking": {"type": "enabled"}}) == "enabled"

    def test_output_config_effort(self) -> None:
        assert extract_thinking_effort({"output_config": {"effort": "low"}}) == "low"

    def test_gemini_thinking_budget(self) -> None:
        result = extract_thinking_effort(
            {"generationConfig": {"thinkingConfig": {"thinkingBudget": 8192}}}
        )
        assert result == "budget:8192"

    def test_metadata_fallback(self) -> None:
        assert extract_thinking_effort(
            {"metadata": {"thinking_effort": "max"}}
        ) == "max"

    def test_empty(self) -> None:
        assert extract_thinking_effort({}) == ""
        assert extract_thinking_effort(None) == ""


# ── extract_usage ───────────────────────────────────────────────────


class TestExtractUsage:
    def test_anthropic_shape(self) -> None:
        u = extract_usage({"usage": {"input_tokens": 100, "output_tokens": 50}})
        assert u == {"input_tokens": 100, "output_tokens": 50}

    def test_openai_shape(self) -> None:
        u = extract_usage({"usage": {"prompt_tokens": 200, "completion_tokens": 80}})
        assert u["input_tokens"] == 200
        assert u["output_tokens"] == 80

    def test_gemini_shape(self) -> None:
        u = extract_usage(
            {"usageMetadata": {"promptTokenCount": 300, "candidatesTokenCount": 120}}
        )
        assert u["input_tokens"] == 300
        assert u["output_tokens"] == 120

    def test_missing_usage(self) -> None:
        u = extract_usage({})
        assert u == {"input_tokens": 0, "output_tokens": 0}


# ── extract_cwd ─────────────────────────────────────────────────────


class TestExtractCwd:
    def test_from_system_message(self) -> None:
        body = {"messages": [{"role": "system", "content": "cwd=/home/user/project"}]}
        assert extract_cwd(body) == "/home/user/project"

    def test_from_instructions(self) -> None:
        body = {"instructions": "working directory: /app/src"}
        assert extract_cwd(body) == "/app/src"

    def test_windows_path(self) -> None:
        body = {"system": "cwd=C:\\Users\\dev\\project"}
        assert extract_cwd(body) == "C:\\Users\\dev\\project"

    def test_empty(self) -> None:
        assert extract_cwd({}) == ""
        assert extract_cwd(None) == ""


# ── extract_trace_entry (integration) ────────────────────────────────


class TestExtractTraceEntry:
    def test_basic(self) -> None:
        entry = extract_trace_entry(
            {"model": "claude-3-opus"},
            {"usage": {"input_tokens": 10, "output_tokens": 5}},
            status_code=200,
            elapsed_ms=123.4,
        )
        assert entry["model"] == "claude-3-opus"
        assert entry["status_code"] == 200
        assert entry["elapsed_ms"] == 123.4
        assert entry["usage"]["input_tokens"] == 10

    def test_with_user_id_and_thinking(self) -> None:
        entry = extract_trace_entry(
            {"model": "gpt-4", "metadata": {"user_id": "u1"}, "reasoning_effort": "high"},
            None,
            headers={"x-session-id": "s1"},
        )
        assert "user_id_hash" in entry
        assert entry["thinking_effort"] == "high"
        assert entry["session_id"] == "s1"

    def test_error_in_response(self) -> None:
        entry = extract_trace_entry(
            {"model": "m"},
            {"error": "rate limited"},
        )
        assert entry["error"] == "rate limited"
