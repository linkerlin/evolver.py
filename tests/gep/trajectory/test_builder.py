"""Tests for evolver.gep.trajectory builder + io (G10.1 foundation slice).

Ports the core of ``evolver/test/trajectoryExport.test.js``: grouping, provider
normalisation, tool-call extraction (Anthropic / OpenAI Responses / Chat
Completions), language detection, failure-correction marking, stats, and the
atomic / symlink-safe / mode-0600 write contract.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from evolver.gep.trajectory import (
    build_trajectories,
    build_trajectory_from_rows,
    write_trajectories,
)
from evolver.gep.trajectory.io import write_trajectories_to_path


def _row(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "prism_compatible": True,
        "createdAtIso": "2026-06-23T01:00:00.000Z",
        "status": 200,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Grouping + Anthropic tool extraction + stats
# ---------------------------------------------------------------------------
def test_groups_rows_into_one_trajectory_per_session() -> None:
    rows = [
        _row(
            requestId="req_a",
            sessionId="sess_1",
            path="/v1/messages",
            upstream="anthropic",
            model="claude-test",
            input_tokens=11,
            output_tokens=7,
            requestBody=json.dumps(
                {
                    "model": "claude-test",
                    "messages": [
                        {"role": "user", "content": "Fix the TypeScript parser test"},
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "tool_1",
                                    "name": "exec_command",
                                    "input": {"cmd": "pnpm test"},
                                }
                            ],
                        },
                    ],
                }
            ),
            responseBody=json.dumps(
                {
                    "id": "msg_1",
                    "stop_reason": "end_turn",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tool_1",
                            "name": "exec_command",
                            "input": {"cmd": "pnpm test"},
                        }
                    ],
                }
            ),
        ),
        _row(
            requestId="req_b",
            sessionId="sess_2",
            path="/v1/responses",
            upstream="openai",
            model="gpt-test",
            requestBody=json.dumps({"model": "gpt-test", "instructions": "Review Python code"}),
            responseBody=json.dumps({"id": "resp_1", "status": "completed"}),
        ),
    ]

    trajectories = build_trajectories(rows)
    assert len(trajectories) == 2
    first = next(t for t in trajectories if t.session_id == "sess_1")
    assert first.schema == "evomap.coding_trajectory.v1"
    assert first.task == "Fix the TypeScript parser test"
    assert first.stats.turns == 1
    assert first.stats.input_tokens == 11
    assert first.stats.output_tokens == 7
    assert first.stats.has_tool_calls is True
    assert first.stats.tool_types.get("exec_command") == 1
    assert "typescript" in first.languages


# ---------------------------------------------------------------------------
# Provider normalisation
# ---------------------------------------------------------------------------
def test_normalizes_bedrock_provider_to_anthropic_taxonomy() -> None:
    trajectory = build_trajectory_from_rows(
        "sess_bedrock",
        [
            _row(
                requestId="r1",
                sessionId="sess_bedrock",
                path="/v1/messages",
                upstream="aws-bedrock",
                model="claude-test",
                requestBody=json.dumps(
                    {"model": "claude-test", "messages": [{"role": "user", "content": "x"}]}
                ),
                responseBody=json.dumps({"content": [{"type": "text", "text": "done"}]}),
            ),
            _row(
                requestId="r2",
                sessionId="sess_bedrock",
                path="/v1/messages",
                provider="aws-bedrock",
                model="claude-test",
                requestBody=json.dumps(
                    {"model": "claude-test", "messages": [{"role": "user", "content": "y"}]}
                ),
                responseBody=json.dumps({"content": [{"type": "text", "text": "done"}]}),
            ),
        ],
    )
    assert trajectory.providers == ["aws-bedrock-anthropic"]
    assert [t.provider for t in trajectory.turns] == [
        "aws-bedrock-anthropic",
        "aws-bedrock-anthropic",
    ]


# ---------------------------------------------------------------------------
# OpenAI Responses tool extraction + language detection
# ---------------------------------------------------------------------------
def test_extracts_tool_calls_and_language_from_openai_responses() -> None:
    trajectory = build_trajectory_from_rows(
        "sess_openai",
        [
            _row(
                requestId="req_openai",
                sessionId="sess_openai",
                path="/v1/responses",
                upstream="openai",
                model="gpt-test",
                responseId="resp_tool",
                previousResponseId="resp_prev",
                requestBody=json.dumps(
                    {
                        "model": "gpt-test",
                        "input": "Patch the Go parser",
                        "previous_response_id": "resp_prev",
                        "tools": [{"type": "function", "name": "exec_command"}],
                    }
                ),
                responseBody=json.dumps(
                    {
                        "id": "resp_tool",
                        "output": [
                            {"type": "function_call", "call_id": "call_1", "name": "exec_command"}
                        ],
                    }
                ),
            )
        ],
    )
    assert trajectory.task == "Patch the Go parser"
    assert trajectory.stats.has_tool_calls is True
    assert trajectory.stats.tool_types.get("exec_command") == 1
    # request-input function_call + response-output function_call
    assert len(trajectory.turns[0].tool_calls) == 2
    assert trajectory.turns[0].response_id == "resp_tool"
    assert trajectory.turns[0].previous_response_id == "resp_prev"
    assert "go" in trajectory.languages


# ---------------------------------------------------------------------------
# Failure-correction marking (Chat Completions)
# ---------------------------------------------------------------------------
def test_marks_failed_turn_as_failure_correction() -> None:
    trajectory = build_trajectory_from_rows(
        "sess_fail",
        [
            _row(
                requestId="req_fail",
                sessionId="sess_fail",
                path="/v1/chat/completions",
                upstream="openai",
                model="gpt-test",
                status=429,
                errorMessage="rate_limit_exceeded",
                requestBody=json.dumps(
                    {"model": "gpt-test", "messages": [{"role": "user", "content": "hello"}]}
                ),
                responseBody=json.dumps({"error": {"type": "rate_limit_exceeded"}}),
            )
        ],
    )
    assert trajectory.stats.has_failure_correction is True
    assert trajectory.turns[0].provider == "openai"
    assert trajectory.turns[0].endpoint == "/v1/chat/completions"


def test_chat_completions_tool_calls_extracted() -> None:
    trajectory = build_trajectory_from_rows(
        "sess_chat",
        [
            _row(
                requestId="req_chat",
                sessionId="sess_chat",
                path="/v1/chat/completions",
                upstream="openai",
                model="gpt-test",
                requestBody=json.dumps(
                    {"model": "gpt-test", "messages": [{"role": "user", "content": "edit main.py"}]}
                ),
                responseBody=json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {
                                            "function": {
                                                "name": "str_replace_editor",
                                                "arguments": "{}",
                                            }
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ),
            )
        ],
    )
    assert trajectory.stats.has_tool_calls is True
    assert trajectory.stats.tool_types.get("str_replace_editor") == 1
    assert "python" in trajectory.languages  # '.py' extension hint


def test_declared_tools_listed_but_not_counted() -> None:
    # Declared tool definitions appear on the turn (declared=True) but do NOT
    # count toward has_tool_calls / tool_call_count / tool_types.
    # count toward has_tool_calls / tool_call_count / tool_types.
    trajectory = build_trajectory_from_rows(
        "sess_declared",
        [
            _row(
                requestId="req_declared",
                sessionId="sess_declared",
                path="/v1/responses",
                upstream="openai",
                model="gpt-test",
                requestBody=json.dumps(
                    {
                        "model": "gpt-test",
                        "input": "Say hello",
                        "tools": [{"type": "function", "name": "exec_command"}],
                    }
                ),
                responseBody=json.dumps(
                    {
                        "id": "resp_plain",
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "content": [{"type": "output_text", "text": "hello"}],
                            }
                        ],
                    }
                ),
            )
        ],
    )
    assert trajectory.stats.has_tool_calls is False
    assert trajectory.stats.tool_call_count == 0
    assert trajectory.stats.tool_types == {}
    assert len(trajectory.turns[0].tool_calls) == 1
    assert trajectory.turns[0].tool_calls[0].declared is True
    # Turn carries the parsed request/response bodies.
    assert trajectory.turns[0].request_body.get("model") == "gpt-test"
    assert trajectory.turns[0].response_body.get("id") == "resp_plain"


# ---------------------------------------------------------------------------
# Streamed tool-argument reconstruction (Anthropic input_json_delta)
# ---------------------------------------------------------------------------
def test_reconstructs_streamed_anthropic_tool_input_json_deltas() -> None:
    cmd = "apply_patch <<PATCH\n*** Begin Patch\nPATCH && node --test test/trajectoryExport.test.js"
    # The streamed input_json_delta fragments concatenate to the JSON-encoded
    # tool input (newlines escaped, so the concatenation is valid JSON).
    full_input = json.dumps({"command": cmd})
    trajectory = build_trajectory_from_rows(
        "sess_stream_delta",
        [
            _row(
                requestId="req_stream_delta",
                sessionId="sess_stream_delta",
                path="/v1/messages",
                upstream="anthropic",
                model="claude-test",
                isStream=True,
                requestBody=json.dumps(
                    {
                        "model": "claude-test",
                        "messages": [{"role": "user", "content": "Patch and test"}],
                    }
                ),
                responseBody=json.dumps(
                    {
                        "reconstructed_stream": True,
                        "events": [
                            {
                                "type": "content_block_start",
                                "index": 1,
                                "content_block": {
                                    "type": "tool_use",
                                    "id": "tool_bash",
                                    "name": "Bash",
                                    "input": {},
                                },
                            },
                            {
                                "type": "content_block_delta",
                                "index": 1,
                                "delta": {
                                    "type": "input_json_delta",
                                    "partial_json": full_input[:40],
                                },
                            },
                            {
                                "type": "content_block_delta",
                                "index": 1,
                                "delta": {
                                    "type": "input_json_delta",
                                    "partial_json": full_input[40:],
                                },
                            },
                            {"type": "content_block_stop", "index": 1},
                        ],
                    }
                ),
            )
        ],
    )
    assert trajectory.stats.has_code_edit is True  # apply_patch / *** Begin Patch
    assert trajectory.stats.has_test_execution is True  # node --test
    assert trajectory.stats.test_commands == [cmd]
    assert len(trajectory.turns[0].tool_calls) == 1
    call = trajectory.turns[0].tool_calls[0]
    assert call.name == "Bash"
    assert call.input["command"] == cmd


# ---------------------------------------------------------------------------
# Streamed OpenAI Chat tool-call argument reconstruction
# ---------------------------------------------------------------------------
def test_reconstructs_streamed_openai_chat_argument_deltas() -> None:
    trajectory = build_trajectory_from_rows(
        "sess_chat_stream_delta",
        [
            _row(
                requestId="req_chat_stream_delta",
                sessionId="sess_chat_stream_delta",
                path="/v1/chat/completions",
                upstream="openai",
                model="gpt-test",
                isStream=True,
                requestBody=json.dumps(
                    {"model": "gpt-test", "messages": [{"role": "user", "content": "Run the test"}]}
                ),
                responseBody=json.dumps(
                    {
                        "reconstructed_stream": True,
                        "events": [
                            {
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {
                                            "tool_calls": [
                                                {
                                                    "index": 0,
                                                    "id": "call_test",
                                                    "type": "function",
                                                    "function": {
                                                        "name": "exec_command",
                                                        "arguments": '{"cmd":"pnpm ',
                                                    },
                                                }
                                            ]
                                        },
                                    }
                                ]
                            },
                            {
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {
                                            "tool_calls": [
                                                {"index": 0, "function": {"arguments": 'test"}'}}
                                            ]
                                        },
                                    }
                                ]
                            },
                        ],
                    }
                ),
            )
        ],
    )
    assert trajectory.stats.has_tool_calls is True
    assert trajectory.stats.has_test_execution is True
    assert trajectory.stats.test_commands == ["pnpm test"]  # parsed cmd value
    assert len(trajectory.turns[0].tool_calls) == 1
    call = trajectory.turns[0].tool_calls[0]
    assert call.function["name"] == "exec_command"
    assert call.function["arguments"] == '{"cmd":"pnpm test"}'


def test_streamed_openai_chat_full_snapshot_does_not_duplicate() -> None:
    # A later delta carrying the FULL arguments (a snapshot) must replace, not
    # append — otherwise the concatenation would be invalid JSON.
    trajectory = build_trajectory_from_rows(
        "sess_chat_stream_snapshot",
        [
            _row(
                requestId="req_chat_stream_snapshot",
                sessionId="sess_chat_stream_snapshot",
                path="/v1/chat/completions",
                upstream="openai",
                model="gpt-test",
                isStream=True,
                requestBody=json.dumps(
                    {"model": "gpt-test", "messages": [{"role": "user", "content": "Run the test"}]}
                ),
                responseBody=json.dumps(
                    {
                        "reconstructed_stream": True,
                        "events": [
                            {
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {
                                            "tool_calls": [
                                                {
                                                    "index": 0,
                                                    "id": "call_test",
                                                    "type": "function",
                                                    "function": {
                                                        "name": "exec_command",
                                                        "arguments": '{"cmd":"pnpm ',
                                                    },
                                                }
                                            ]
                                        },
                                    }
                                ]
                            },
                            {
                                "choices": [
                                    {
                                        "index": 0,
                                        "delta": {
                                            "tool_calls": [
                                                {
                                                    "index": 0,
                                                    "function": {
                                                        "arguments": '{"cmd":"pnpm test"}'
                                                    },
                                                }
                                            ]
                                        },
                                    }
                                ]
                            },
                        ],
                    }
                ),
            )
        ],
    )
    assert trajectory.stats.has_test_execution is True
    assert trajectory.stats.test_commands == ["pnpm test"]
    assert len(trajectory.turns[0].tool_calls) == 1
    assert trajectory.turns[0].tool_calls[0].function["arguments"] == '{"cmd":"pnpm test"}'


# ---------------------------------------------------------------------------
# Streamed OpenAI Responses function-call argument reconstruction
# ---------------------------------------------------------------------------
def test_reconstructs_streamed_openai_responses_argument_deltas() -> None:
    trajectory = build_trajectory_from_rows(
        "sess_responses_stream_delta",
        [
            _row(
                requestId="req_responses_stream_delta",
                sessionId="sess_responses_stream_delta",
                path="/v1/responses",
                upstream="openai",
                model="gpt-test",
                isStream=True,
                requestBody=json.dumps({"model": "gpt-test", "input": "Run the test"}),
                responseBody=json.dumps(
                    {
                        "reconstructed_stream": True,
                        "events": [
                            {
                                "type": "response.output_item.added",
                                "output_index": 0,
                                "item": {
                                    "id": "fc_1",
                                    "type": "function_call",
                                    "call_id": "call_test",
                                    "name": "exec_command",
                                    "arguments": "",
                                },
                            },
                            {
                                "type": "response.function_call_arguments.delta",
                                "output_index": 0,
                                "item_id": "fc_1",
                                "delta": '{"cmd":"pnpm ',
                            },
                            {
                                "type": "response.function_call_arguments.delta",
                                "output_index": 0,
                                "item_id": "fc_1",
                                "delta": 'test"}',
                            },
                            {
                                "type": "response.function_call_arguments.done",
                                "output_index": 0,
                                "item_id": "fc_1",
                                "arguments": '{"cmd":"pnpm test"}',
                            },
                            {
                                "type": "response.output_item.done",
                                "output_index": 0,
                                "item": {
                                    "id": "fc_1",
                                    "type": "function_call",
                                    "call_id": "call_test",
                                    "name": "exec_command",
                                    "arguments": "",
                                },
                            },
                        ],
                    }
                ),
            )
        ],
    )
    assert trajectory.stats.has_tool_calls is True
    assert trajectory.stats.has_test_execution is True
    assert trajectory.stats.test_commands == ["pnpm test"]
    assert len(trajectory.turns[0].tool_calls) == 1
    assert trajectory.turns[0].tool_calls[0].name == "exec_command"
    assert trajectory.turns[0].tool_calls[0].input["cmd"] == "pnpm test"


# ---------------------------------------------------------------------------
# I/O: atomic, symlink-safe, mode-0600 write
# ---------------------------------------------------------------------------
def test_write_trajectories_roundtrip(tmp_path: Path) -> None:
    inp = tmp_path / "trace.jsonl"
    inp.write_text(
        json.dumps(
            _row(
                requestId="r1",
                sessionId="s1",
                path="/v1/messages",
                upstream="anthropic",
                model="claude-test",
                requestBody=json.dumps(
                    {"messages": [{"role": "user", "content": "Build the Rust service"}]}
                ),
                responseBody=json.dumps({"content": [{"type": "text", "text": "ok"}]}),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.jsonl"
    trajectories = write_trajectories(input_path=inp, output_path=out)
    assert len(trajectories) == 1
    assert trajectories[0].session_id == "s1"

    written = out.read_text(encoding="utf-8").splitlines()
    assert len(written) == 1
    record = json.loads(written[0])
    assert record["schema"] == "evomap.coding_trajectory.v1"
    assert record["session_id"] == "s1"
    assert record["task"] == "Build the Rust service"
    assert "rust" in record["languages"]


def test_write_does_not_follow_preplaced_symlink(tmp_path: Path) -> None:
    # PR #294 C4: a symlink at the output path must not let us clobber its target.
    sensitive = tmp_path / "sensitive.txt"
    sensitive.write_text("ORIGINAL", encoding="utf-8")
    out = tmp_path / "out.jsonl"
    out.symlink_to(sensitive)

    write_trajectories_to_path(out, [])

    # The sensitive target is untouched.
    assert sensitive.read_text(encoding="utf-8") == "ORIGINAL"
    # The output is now a real regular file (symlink replaced).
    st = out.lstat()
    assert not stat.S_ISLNK(st.st_mode)
    assert stat.S_ISREG(st.st_mode)
    if os.name != "nt":
        assert (st.st_mode & 0o777) == 0o600
