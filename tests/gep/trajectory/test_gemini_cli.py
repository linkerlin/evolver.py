"""Gemini CLI runtime adapter tests (Sprint 15.3 / FIX-3)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from evolver.gep.trajectory.gemini_cli import GEMINI_CLI_FILE_RE, is_gemini_cli_path
from evolver.gep.trajectory.inputs import read_trajectory_inputs_detailed
from evolver.gep.trajectory.marked_gate import collect_runtime_session_inputs

JSONL_LINES = [
    {
        "sessionId": "sess-1",
        "projectHash": "abc",
        "startTime": "2026-05-16T04:30:00.000Z",
        "kind": "main",
    },
    {
        "id": "u1",
        "timestamp": "2026-05-16T04:30:10.000Z",
        "type": "user",
        "content": [{"text": "Run the unit tests please"}],
    },
    {"$set": {"lastUpdated": "2026-05-16T04:30:10.000Z"}},
    {
        "id": "g1",
        "timestamp": "2026-05-16T04:30:20.000Z",
        "type": "gemini",
        "content": "Running them now.",
        "thoughts": [{"subject": "Plan", "description": "I should invoke the test runner."}],
        "toolCalls": [
            {
                "id": "tool-1",
                "name": "run_shell_command",
                "args": {"command": "npm test"},
                "result": [
                    {
                        "functionResponse": {
                            "id": "tool-1",
                            "name": "run_shell_command",
                            "response": {"output": "All tests passed"},
                        }
                    }
                ],
                "status": "success",
            }
        ],
        "tokens": {"input": 100, "output": 20, "total": 120},
        "model": "gemini-3-pro",
    },
    {
        "id": "info-1",
        "timestamp": "2026-05-16T04:30:25.000Z",
        "type": "info",
        "content": "Gemini CLI update available!",
    },
]


def _gemini_session_dir(tmp_path: Path) -> Path:
    chats = tmp_path / ".gemini" / "tmp" / "demo-project" / "chats"
    chats.mkdir(parents=True)
    return chats


def test_jsonl_extracts_user_thinking_tools(tmp_path: Path) -> None:
    chats = _gemini_session_dir(tmp_path)
    file = chats / "session-2026-05-16T04-30-aaaa.jsonl"
    file.write_text("\n".join(json.dumps(line) for line in JSONL_LINES) + "\n", encoding="utf-8")

    res = read_trajectory_inputs_detailed(file)
    assert len(res["sessionTrajectories"]) == 1
    t = res["sessionTrajectories"][0]
    assert t.source_agent == "gemini-cli"
    assert t.client_source == "gemini-cli"
    assert t.session_model == "gemini-3-pro"
    assert t.task == "Run the unit tests please"
    assert t.stats.has_tool_calls is True
    assert t.stats.tool_types.get("run_shell_command") == 1
    reasoning = [turn for turn in t.turns if turn.reasoning]
    assert reasoning
    assert "invoke the test runner" in json.dumps([r.reasoning for r in reasoning])
    blob = json.dumps([turn.__dict__ for turn in t.turns], default=str)
    assert "All tests passed" in blob
    assert t.stats.input_tokens == 100
    assert t.stats.output_tokens == 20
    assert "Gemini CLI update available" not in blob


def test_json_variant_with_messages(tmp_path: Path) -> None:
    chats = _gemini_session_dir(tmp_path)
    file = chats / "session-2026-04-28T05-44-bbbb.json"
    session = {
        "sessionId": "sess-json",
        "projectHash": "def",
        "messages": [line for line in JSONL_LINES if line.get("type")],
    }
    file.write_text(json.dumps(session, indent=2), encoding="utf-8")
    res = read_trajectory_inputs_detailed(file)
    assert len(res["sessionTrajectories"]) == 1
    t = res["sessionTrajectories"][0]
    assert t.source_agent == "gemini-cli"
    assert t.stats.has_tool_calls is True
    assert t.task == "Run the unit tests please"


def test_detect_scoped_to_session_files() -> None:
    re_pat = GEMINI_CLI_FILE_RE
    assert re_pat.search("/home/u/.gemini/tmp/proj/logs.json") is None
    assert re_pat.search("/home/u/.gemini/tmp/proj/chats/logs.json") is None
    assert re_pat.search("/home/u/.gemini/tmp/proj/chats/session-x.jsonl") is not None
    assert re_pat.search("/home/u/.gemini/tmp/proj/chats/session-x.json") is not None
    assert is_gemini_cli_path(r"C:\Users\u\.gemini\tmp\p\chats\session-x.jsonl")


def test_auto_discovery_json_and_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chats = tmp_path / ".gemini" / "tmp" / "demo-project" / "chats"
    chats.mkdir(parents=True)
    records = [line for line in JSONL_LINES if line.get("type")]
    (chats / "session-2026-05-16T04-30-aaaa.jsonl").write_text(
        "\n".join(json.dumps(line) for line in JSONL_LINES) + "\n", encoding="utf-8"
    )
    (chats / "session-2026-04-28T05-44-bbbb.json").write_text(
        json.dumps({"sessionId": "s-json", "messages": records}, indent=2),
        encoding="utf-8",
    )
    gemini_tmp = tmp_path / ".gemini" / "tmp"
    opts = {
        "runtimeSessions": 1,
        "homedir": str(tmp_path),
        "runtimeSessionDirs": [str(gemini_tmp)],
        "workspaceRoot": str(tmp_path / "no-such-workspace"),
        "includeUnmarked": 1,
        "markedSessionsFile": str(tmp_path / "marked-sessions.jsonl"),
    }
    discovered = collect_runtime_session_inputs(opts)
    gemini_files = [
        f for f in discovered["files"] if re.search(r"\.gemini[/\\]tmp[/\\]", f["path"])
    ]
    assert len(gemini_files) == 2
    assert any(f["path"].endswith(".json") for f in gemini_files)
    assert any(f["path"].endswith(".jsonl") for f in gemini_files)

    monkeypatch.setenv("EVOMAP_PROXY_TRACE_FILE", str(tmp_path / "proxy-traces.jsonl"))
    res = read_trajectory_inputs_detailed(None, opts)
    built = [t for t in res["sessionTrajectories"] if t.source_agent == "gemini-cli"]
    assert len(built) == 2
    assert all(t.stats.turns > 0 for t in built)
