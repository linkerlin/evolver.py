"""Sprint 15.6 — multi-agent sessionFormat contracts (ports sessionFormat.test.js)."""

from __future__ import annotations

import json

from evolver.evolve.pipeline.session_format import (
    format_cursor_transcript,
    format_session_log,
)


class TestOpenClaw:
    def test_parses_tool_call_content(self) -> None:
        jsonl = "\n".join(
            [
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "user",
                            "content": [{"type": "text", "text": "deploy the fix"}],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "running deploy"},
                                {"type": "toolCall", "name": "shell"},
                            ],
                        },
                    }
                ),
            ]
        )
        out = format_session_log(jsonl)
        assert "**USER**: deploy the fix" in out
        assert "**ASSISTANT**: running deploy [TOOL: shell]" in out

    def test_captures_error_message(self) -> None:
        jsonl = json.dumps(
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": "ok",
                    "errorMessage": "Unsupported MIME type: image/gif",
                },
            }
        )
        out = format_session_log(jsonl)
        assert "[LLM ERROR]" in out
        assert "Unsupported MIME" in out

    def test_filters_heartbeat_and_no_reply(self) -> None:
        jsonl = "\n".join(
            [
                json.dumps(
                    {"type": "message", "message": {"role": "user", "content": "HEARTBEAT_OK"}}
                ),
                json.dumps(
                    {"type": "message", "message": {"role": "assistant", "content": "NO_REPLY"}}
                ),
                json.dumps(
                    {
                        "type": "message",
                        "message": {"role": "user", "content": "real question"},
                    }
                ),
            ]
        )
        out = format_session_log(jsonl)
        assert "HEARTBEAT_OK" not in out
        assert "NO_REPLY" not in out
        assert "real question" in out

    def test_tool_result_entries(self) -> None:
        jsonl = json.dumps(
            {
                "type": "message",
                "message": {"role": "toolResult"},
                "content": "Command exited with error code 1: ENOENT",
            }
        )
        out = format_session_log(jsonl)
        assert "[TOOL RESULT]" in out
        assert "ENOENT" in out


class TestClaudeCode:
    def test_parses_tool_use(self) -> None:
        jsonl = "\n".join(
            [
                json.dumps(
                    {
                        "type": "user",
                        "uuid": "u1",
                        "message": {
                            "role": "user",
                            "content": [{"type": "text", "text": "fix the bug"}],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "a1",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {"type": "text", "text": "analyzing"},
                                {
                                    "type": "tool_use",
                                    "name": "Bash",
                                    "id": "t1",
                                    "input": {"command": "ls"},
                                },
                            ],
                        },
                    }
                ),
            ]
        )
        out = format_session_log(jsonl)
        assert "**USER**: fix the bug" in out
        assert "**ASSISTANT**: analyzing [TOOL: Bash]" in out

    def test_skips_is_meta(self) -> None:
        jsonl = json.dumps(
            {
                "type": "assistant",
                "isMeta": True,
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "internal meta"}],
                },
            }
        )
        assert format_session_log(jsonl).strip() == ""

    def test_tool_result_error(self) -> None:
        jsonl = json.dumps({"type": "tool_result", "content": "Error: EACCES permission denied"})
        out = format_session_log(jsonl)
        assert "[TOOL RESULT]" in out
        assert "EACCES" in out

    def test_skips_thinking_blocks(self) -> None:
        jsonl = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "let me think..."},
                        {"type": "text", "text": "the answer is 42"},
                    ],
                },
            }
        )
        out = format_session_log(jsonl)
        assert "let me think" not in out
        assert "the answer is 42" in out


class TestCursorJsonl:
    def test_role_based_entries(self) -> None:
        jsonl = "\n".join(
            [
                json.dumps(
                    {
                        "role": "user",
                        "message": {"content": [{"type": "text", "text": "check the logs"}]},
                    }
                ),
                json.dumps(
                    {
                        "role": "assistant",
                        "message": {
                            "content": [
                                {"type": "text", "text": "reading logs now"},
                                {
                                    "type": "tool_use",
                                    "name": "Shell",
                                    "input": {"command": "tail -f"},
                                },
                            ]
                        },
                    }
                ),
            ]
        )
        out = format_session_log(jsonl)
        assert "**USER**: check the logs" in out
        assert "**ASSISTANT**: reading logs now [TOOL: Shell]" in out

    def test_assistant_only_tools(self) -> None:
        jsonl = json.dumps(
            {
                "role": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Read", "input": {"path": "/tmp/file.txt"}},
                        {"type": "tool_use", "name": "Grep", "input": {"pattern": "error"}},
                    ]
                },
            }
        )
        out = format_session_log(jsonl)
        assert "[TOOL: Read]" in out
        assert "[TOOL: Grep]" in out


class TestCodex:
    def test_item_added_user(self) -> None:
        jsonl = json.dumps(
            {
                "type": "item.added",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "refactor the module"}],
                },
            }
        )
        assert "**USER**: refactor the module" in format_session_log(jsonl)

    def test_item_completed_assistant(self) -> None:
        jsonl = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "done, 3 files changed"}],
                },
            }
        )
        assert "**ASSISTANT**: done, 3 files changed" in format_session_log(jsonl)

    def test_function_call(self) -> None:
        jsonl = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "function_call",
                    "name": "shell",
                    "call_id": "call_123",
                    "arguments": '{"cmd":"ls"}',
                },
            }
        )
        assert "[TOOL: shell]" in format_session_log(jsonl)

    def test_function_call_output(self) -> None:
        jsonl = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "function_call_output",
                    "output": "README.md\npackage.json\nsrc/",
                },
            }
        )
        out = format_session_log(jsonl)
        assert "[TOOL RESULT]" in out
        assert "README.md" in out

    def test_skips_short_success_output(self) -> None:
        jsonl = json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "function_call_output", "output": "success"},
            }
        )
        assert format_session_log(jsonl).strip() == ""

    def test_skips_session_created(self) -> None:
        jsonl = json.dumps({"type": "session.created", "session_id": "sess_abc"})
        assert format_session_log(jsonl).strip() == ""

    def test_content_array_function_call(self) -> None:
        jsonl = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "let me check"},
                        {"type": "function_call", "name": "read_file"},
                    ],
                },
            }
        )
        out = format_session_log(jsonl)
        assert "let me check" in out
        assert "[TOOL: read_file]" in out


class TestManus:
    def test_user_message(self) -> None:
        jsonl = json.dumps(
            {
                "type": "user_message",
                "id": "evt_1",
                "user_message": {
                    "content": "build a landing page",
                    "message_type": "text",
                },
            }
        )
        assert "**USER**: build a landing page" in format_session_log(jsonl)

    def test_assistant_message(self) -> None:
        jsonl = json.dumps(
            {
                "type": "assistant_message",
                "assistant_message": {
                    "content": "Created index.html with responsive design",
                    "attachments": [],
                },
            }
        )
        assert "**ASSISTANT**: Created index.html" in format_session_log(jsonl)

    def test_tool_used(self) -> None:
        jsonl = json.dumps(
            {
                "type": "tool_used",
                "tool_used": {
                    "name": "browser",
                    "input": "navigate to http://localhost:3000",
                },
            }
        )
        assert "[TOOL: browser]" in format_session_log(jsonl)

    def test_skips_status_update(self) -> None:
        jsonl = json.dumps({"type": "status_update", "status_update": {"agent_status": "thinking"}})
        assert format_session_log(jsonl).strip() == ""


class TestEdgeCases:
    def test_mixed_formats(self) -> None:
        jsonl = "\n".join(
            [
                json.dumps(
                    {"type": "message", "message": {"role": "user", "content": "openclaw msg"}}
                ),
                json.dumps(
                    {
                        "role": "user",
                        "message": {"content": [{"type": "text", "text": "cursor msg"}]},
                    }
                ),
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": [{"type": "text", "text": "claude msg"}],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.added",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "codex msg"}],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "user_message",
                        "user_message": {"content": "manus msg"},
                    }
                ),
            ]
        )
        out = format_session_log(jsonl)
        for msg in ("openclaw msg", "cursor msg", "claude msg", "codex msg", "manus msg"):
            assert msg in out

    def test_skips_malformed(self) -> None:
        jsonl = (
            "not json\n"
            '{"type":"user","message":{"content":[{"type":"text","text":"valid"}]}}\n'
            "{broken"
        )
        assert "valid" in format_session_log(jsonl)

    def test_deduplicates(self) -> None:
        line = json.dumps(
            {
                "type": "user",
                "message": {"content": [{"type": "text", "text": "same"}]},
            }
        )
        jsonl = "\n".join([line] * 4)
        out = format_session_log(jsonl)
        assert "Repeated 3 times" in out

    def test_empty_content(self) -> None:
        jsonl = json.dumps({"role": "assistant", "message": {"content": []}})
        assert format_session_log(jsonl).strip() == ""

    def test_string_content(self) -> None:
        jsonl = json.dumps({"role": "user", "message": {"content": "plain string content"}})
        assert "plain string content" in format_session_log(jsonl)


class TestFormatCursorTranscript:
    def test_parses_user_assistant_blocks(self) -> None:
        raw = "user:\nhow do I fix this?\nA:\nYou need to update the config.\n"
        out = format_cursor_transcript(raw)
        assert "user:" in out
        assert "how do I fix this?" in out
        assert "A:" in out
        assert "update the config" in out

    def test_keeps_tool_call_skips_params(self) -> None:
        raw = (
            "A:\n[Tool call] Shell\n  command: ls -la\n  description: list files\n"
            "[Tool result]\nREADME.md\nA:\ndone\n"
        )
        out = format_cursor_transcript(raw)
        assert "[Tool call] Shell" in out
        assert "command: ls" not in out
        assert "README.md" not in out
        assert "done" in out

    def test_skips_xml_tags(self) -> None:
        raw = "user:\n<user_query>\nwhat is this?\n</user_query>\n"
        out = format_cursor_transcript(raw)
        assert "<user_query>" not in out
        assert "what is this?" in out
