"""Session-log source tests (G10.1 slice 3a): Codex rollout + Claude Code.

Ports the Codex / Claude Code transcript contracts from
``evolver/test/trajectoryExport.test.js``: source classification, runtime
session trajectories with reasoning turns, tool-call extraction (incl. custom
tool calls + tool search), and test-execution / code-edit / failure-correction
detection.
"""

from __future__ import annotations

from pathlib import Path

from evolver.gep.trajectory import (
    build_claude_code_trajectory,
    build_codex_trajectory,
    build_generic_chat_trajectory,
    build_trajectory_from_session_log,
    detect_source,
)

_CODEX_RECORDS = [
    {
        "timestamp": "2026-06-24T01:02:03.000Z",
        "type": "session_meta",
        "payload": {"id": "codex-session-1", "cwd": "/tmp/work"},
    },
    {
        "timestamp": "2026-06-24T01:02:04.000Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Fix the TypeScript test and run pnpm test."}
            ],
        },
    },
    {
        "timestamp": "2026-06-24T01:02:05.000Z",
        "type": "response_item",
        "payload": {
            "type": "reasoning",
            "model": "gpt-5-codex",
            "usage": {"input_tokens": 13, "output_tokens": 2},
            "summary": [{"text": "Need inspect then test."}],
            "encrypted_content": "codex-encrypted-content",
        },
    },
    {
        "timestamp": "2026-06-24T01:02:06.000Z",
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "shell_command",
            "call_id": "call_test",
            "arguments": '{"command":"pnpm test"}',
        },
    },
    {
        "timestamp": "2026-06-24T01:02:07.000Z",
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "call_id": "call_test",
            "output": "Exit code: 1\nOutput:\n1 failed",
        },
    },
    {
        "timestamp": "2026-06-24T01:02:08.000Z",
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call",
            "name": "apply_patch",
            "call_id": "call_patch",
            "input": "*** Begin Patch\n*** End Patch",
        },
    },
    {
        "timestamp": "2026-06-24T01:02:09.000Z",
        "type": "response_item",
        "payload": {
            "type": "tool_search_call",
            "id": "call_search",
            "query": "confirmed high jsonl",
            "filters": {"repo": "evolver"},
        },
    },
    {
        "timestamp": "2026-06-24T01:02:10.000Z",
        "type": "response_item",
        "payload": {
            "type": "tool_search_output",
            "call_id": "call_search",
            "results": [{"title": "Keep native tool events"}],
        },
    },
]


def test_detect_source_classifies_codex_and_claude() -> None:
    assert detect_source(_CODEX_RECORDS[:1], "rollout.jsonl") == "codex"
    assert detect_source(_CODEX_RECORDS, "rollout.jsonl") == "codex"
    claude = [{"type": "user", "message": {"content": [{"type": "text", "text": "hi"}]}}]
    assert detect_source(claude, "x.transcript.jsonl") == "claude_code"
    assert detect_source([{"requestId": "r", "path": "/v1/messages"}], "trace.jsonl") is None


def test_codex_session_trajectory() -> None:
    traj = build_codex_trajectory(_CODEX_RECORDS, source_path="/work/rollout.jsonl")
    assert traj.session_id == "codex-session-1"
    assert traj.source_kind == "runtime_session"
    assert traj.source_agent == "codex"
    assert traj.source_path == "/work/rollout.jsonl"
    assert "Fix the TypeScript test" in traj.task

    assert traj.stats.has_test_execution is True
    assert traj.stats.has_code_edit is True
    assert traj.stats.has_failure_correction is True
    assert traj.stats.input_tokens == 13
    assert traj.stats.output_tokens == 2
    assert traj.stats.tool_types == {
        "shell_command": 1,
        "apply_patch": 1,
        "tool_search_call": 1,
    }

    reasoning_turn = next(t for t in traj.turns if t.reasoning == "Need inspect then test.")
    assert reasoning_turn.model == "gpt-5-codex"
    assert reasoning_turn.input_tokens == 13
    assert reasoning_turn.output_tokens == 2
    assert reasoning_turn.encrypted_content == "codex-encrypted-content"

    # A turn carries the failing tool output.
    assert any("1 failed" in (t.error or "") for t in traj.turns)

    # shell_command call keeps the raw arguments string as input.
    shell = next(c for t in traj.turns for c in t.tool_calls if c.name == "shell_command")
    assert shell.input == '{"command":"pnpm test"}'

    # tool_search_call preserves id + query.
    search = next(c for t in traj.turns for c in t.tool_calls if c.name == "tool_search_call")
    assert search.id == "call_search"
    assert search.input["query"] == "confirmed high jsonl"

    # tool_search_output turn carries the tool_name/tool_use_id on response_body.
    out_turn = next(
        t
        for t in traj.turns
        if t.response_body.get("tool_name") == "tool_search_output"
        and t.response_body.get("tool_use_id") == "call_search"
    )
    assert out_turn is not None
    assert "typescript" in traj.languages  # task mentions TypeScript + pnpm


_CLAUDE_RECORDS = [
    {
        "timestamp": "2026-06-24T02:00:00.000Z",
        "type": "user",
        "message": {"content": [{"type": "text", "text": "Patch foo.py and run pytest."}]},
    },
    {
        "timestamp": "2026-06-24T02:00:01.000Z",
        "type": "assistant",
        "message": {
            "model": "claude-opus-4-20250514",
            "usage": {"input_tokens": 17, "output_tokens": 23},
            "content": [
                {
                    "type": "thinking",
                    "thinking": "Need inspect first.",
                    "signature": "claude-thinking-signature",
                    "encrypted_signature": "claude-encrypted-signature",
                },
                {"type": "tool_use", "id": "tu_1", "name": "Bash", "input": {"command": "pytest"}},
            ],
        },
    },
    {
        "timestamp": "2026-06-24T02:00:02.000Z",
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tu_1",
                    "content": "Exit code: 1\npytest failed",
                    "is_error": True,
                }
            ]
        },
    },
]


def test_claude_code_session_trajectory() -> None:
    traj = build_claude_code_trajectory(_CLAUDE_RECORDS, source_path="/.claude/x.transcript.jsonl")
    assert traj.source_kind == "runtime_session"
    assert traj.source_agent == "claude_code"
    assert "Patch foo.py and run pytest." in traj.task
    assert traj.stats.input_tokens == 17
    assert traj.stats.output_tokens == 23
    assert traj.stats.has_test_execution is True  # Bash pytest
    assert traj.stats.has_failure_correction is True  # is_error tool_result
    assert traj.stats.tool_types == {"Bash": 1}
    assert "anthropic" in traj.providers

    assistant = next(t for t in traj.turns if t.model == "claude-opus-4-20250514")
    assert assistant.reasoning == "Need inspect first."
    assert assistant.encrypted_content == "claude-encrypted-signature"
    assert assistant.tool_calls[0].name == "Bash"
    assert assistant.tool_calls[0].id == "tu_1"
    assert assistant.tool_calls[0].input == {"command": "pytest"}

    result_turn = next(t for t in traj.turns if t.response_body.get("tool_name") == "tool_result")
    assert result_turn.is_failure_correction is True
    assert "pytest failed" in (result_turn.error or "")
    assert "python" in traj.languages  # foo.py + pytest


def test_build_trajectory_from_session_log_dispatches(tmp_path: Path) -> None:
    codex = tmp_path / "rollout.jsonl"
    codex.write_text(
        "\n".join(__import__("json").dumps(r) for r in _CODEX_RECORDS) + "\n", encoding="utf-8"
    )
    traj = build_trajectory_from_session_log(codex)
    assert traj is not None
    assert traj.source_agent == "codex"
    assert traj.session_id == "codex-session-1"


_GENERIC_RECORDS = [
    {"role": "system", "content": "You are a careful coding assistant."},
    {"role": "user", "content": "Fix the TypeScript test and run pnpm test."},
    {
        "role": "assistant",
        "model": "gpt-generic-runtime",
        "usage": {"prompt_tokens": 5, "completion_tokens": 7},
        "content": [
            {
                "type": "thinking",
                "thinking": "Need run tests.",
                "signature": "generic-thinking-signature",
            }
        ],
    },
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_run_tests",
                "type": "function",
                "function": {"name": "exec_command", "arguments": '{"cmd":"pnpm test"}'},
            }
        ],
    },
    {"role": "tool", "tool_call_id": "call_run_tests", "content": "Exit code: 0\nTests passed"},
]


def test_generic_chat_session_trajectory() -> None:
    traj = build_generic_chat_trajectory(_GENERIC_RECORDS, source_path="/s.messages.jsonl")
    assert traj.source_kind == "runtime_session"
    assert traj.source_agent == "generic-chat"
    assert traj.task == "Fix the TypeScript test and run pnpm test."
    assert traj.stats.input_tokens == 5  # prompt_tokens
    assert traj.stats.output_tokens == 7  # completion_tokens
    assert traj.stats.has_tool_calls is True
    assert traj.stats.tool_types == {"exec_command": 1}
    assert traj.stats.has_test_execution is True
    assert traj.stats.test_commands == ["pnpm test"]  # parsed cmd value

    reasoning = next(t for t in traj.turns if t.reasoning == "Need run tests.")
    assert reasoning.model == "gpt-generic-runtime"
    assert reasoning.reasoning_signature == "generic-thinking-signature"

    call = next(c for t in traj.turns for c in t.tool_calls if c.id == "call_run_tests")
    assert call.function["name"] == "exec_command"
    assert call.function["arguments"] == '{"cmd":"pnpm test"}'
    assert "typescript" in traj.languages
