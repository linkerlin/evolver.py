"""Kimi CLI wire.jsonl adapter tests (Sprint 15.3 / FIX-5)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from evolver.gep.trajectory.inputs import read_trajectory_inputs_detailed
from evolver.gep.trajectory.marked_gate import collect_runtime_session_inputs


def _kimi_wire_file(tmp_path: Path, lines: list[dict]) -> Path:
    directory = tmp_path / ".kimi" / "sessions" / "workspacehash" / "sess-id"
    directory.mkdir(parents=True)
    file = directory / "wire.jsonl"
    file.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return file


def test_parses_user_thinking_tools(tmp_path: Path) -> None:
    file = _kimi_wire_file(
        tmp_path,
        [
            {"type": "metadata", "protocol_version": "1.10"},
            {
                "timestamp": 1779370805.04,
                "message": {
                    "type": "TurnBegin",
                    "payload": {"user_input": [{"type": "text", "text": "Read the README"}]},
                },
            },
            {
                "timestamp": 1779370806.0,
                "message": {
                    "type": "ContentPart",
                    "payload": {"type": "think", "think": "I should read the file first."},
                },
            },
            {
                "timestamp": 1779370806.5,
                "message": {
                    "type": "ContentPart",
                    "payload": {"type": "text", "text": "Sure, reading it."},
                },
            },
            {
                "timestamp": 1779370807.0,
                "message": {
                    "type": "ToolCall",
                    "payload": {
                        "type": "function",
                        "id": "tool_1",
                        "function": {
                            "name": "ReadFile",
                            "arguments": '{"path":"README.md"}',
                        },
                    },
                },
            },
            {
                "timestamp": 1779370808.0,
                "message": {
                    "type": "ToolResult",
                    "payload": {
                        "tool_call_id": "tool_1",
                        "return_value": {
                            "is_error": False,
                            "output": "# Title\nbody",
                        },
                    },
                },
            },
            {"timestamp": 1779370809.0, "message": {"type": "TurnEnd", "payload": {}}},
        ],
    )
    res = read_trajectory_inputs_detailed(file)
    assert len(res["sessionTrajectories"]) == 1
    t = res["sessionTrajectories"][0]
    assert t.source_agent == "kimi"
    assert t.client_source == "kimi-cli"
    assert t.task == "Read the README"
    assert t.stats.has_tool_calls is True
    assert t.stats.tool_types.get("ReadFile") == 1
    reasoning = [x for x in t.turns if x.reasoning]
    assert reasoning
    assert "read the file first" in json.dumps([r.reasoning for r in reasoning])
    blob = json.dumps([turn.__dict__ for turn in t.turns], default=str)
    assert "# Title" in blob


def test_error_tool_result_flagged(tmp_path: Path) -> None:
    file = _kimi_wire_file(
        tmp_path,
        [
            {"type": "metadata", "protocol_version": "1.10"},
            {
                "timestamp": 1,
                "message": {
                    "type": "TurnBegin",
                    "payload": {"user_input": [{"type": "text", "text": "run it"}]},
                },
            },
            {
                "timestamp": 2,
                "message": {
                    "type": "ToolCall",
                    "payload": {
                        "id": "c1",
                        "function": {"name": "Shell", "arguments": '{"cmd":"false"}'},
                    },
                },
            },
            {
                "timestamp": 3,
                "message": {
                    "type": "ToolResult",
                    "payload": {
                        "tool_call_id": "c1",
                        "return_value": {"is_error": True, "output": "exit 1"},
                    },
                },
            },
        ],
    )
    res = read_trajectory_inputs_detailed(file)
    t = res["sessionTrajectories"][0]
    blob = json.dumps([turn.__dict__ for turn in t.turns], default=str)
    assert '"error": "exit 1"' in blob or '"error":"exit 1"' in blob


def test_auto_discovery_unrelated_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / ".kimi" / "sessions" / "a1b2c3workspacehash" / "sess-discover-1"
    directory.mkdir(parents=True)
    (directory / "wire.jsonl").write_text(
        "\n".join(
            json.dumps(line)
            for line in [
                {"type": "metadata", "protocol_version": "1.10"},
                {
                    "timestamp": 1779370805.04,
                    "message": {
                        "type": "TurnBegin",
                        "payload": {"user_input": [{"type": "text", "text": "List the files"}]},
                    },
                },
                {
                    "timestamp": 1779370806.0,
                    "message": {
                        "type": "ContentPart",
                        "payload": {"type": "think", "think": "I will list them."},
                    },
                },
                {
                    "timestamp": 1779370807.0,
                    "message": {
                        "type": "ToolCall",
                        "payload": {
                            "id": "tool_1",
                            "function": {
                                "name": "ListDir",
                                "arguments": '{"path":"."}',
                            },
                        },
                    },
                },
                {
                    "timestamp": 1779370808.0,
                    "message": {
                        "type": "ToolResult",
                        "payload": {
                            "tool_call_id": "tool_1",
                            "return_value": {
                                "is_error": False,
                                "output": "a.txt\nb.txt",
                            },
                        },
                    },
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    kimi_sessions = tmp_path / ".kimi" / "sessions"
    opts = {
        "runtimeSessions": 1,
        "homedir": str(tmp_path),
        "runtimeSessionDirs": [str(kimi_sessions)],
        "workspaceRoot": str(tmp_path / "no-such-unrelated-workspace"),
        "includeUnmarked": 1,
        "markedSessionsFile": str(tmp_path / "marked-sessions.jsonl"),
    }
    discovered = collect_runtime_session_inputs(opts)
    kimi_files = [
        f for f in discovered["files"] if re.search(r"\.kimi[/\\]sessions[/\\]", f["path"])
    ]
    assert len(kimi_files) == 1

    monkeypatch.setenv("EVOMAP_PROXY_TRACE_FILE", str(tmp_path / "proxy-traces.jsonl"))
    res = read_trajectory_inputs_detailed(None, opts)
    built = [x for x in res["sessionTrajectories"] if x.source_agent == "kimi"]
    assert len(built) == 1
    assert built[0].task == "List the files"
    assert built[0].stats.turns > 0
    assert built[0].stats.tool_types.get("ListDir") == 1
