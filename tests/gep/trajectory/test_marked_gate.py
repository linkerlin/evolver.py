"""Marked-session discovery gate (Sprint 15.3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.gep.trajectory.marked_gate import collect_runtime_session_inputs
from evolver.proxy.trace.extractor import hash_trace_value


def _write_claude_session(home: Path, session_id: str) -> Path:
    directory = home / ".claude" / "projects" / "proj"
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / f"{session_id}.jsonl"
    file.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {
                    "type": "user",
                    "cwd": str(home),
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Please do a real task, not a meta marker.",
                            }
                        ],
                    },
                },
                {
                    "type": "assistant",
                    "cwd": str(home),
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "text",
                                "text": "Done, here is the real assistant content.",
                            }
                        ],
                    },
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return file


def _discovered_ids(opts: dict) -> list[str]:
    files = collect_runtime_session_inputs(opts)["files"]
    return sorted(Path(f["path"]).name.replace(".jsonl", "").replace(".json", "") for f in files)


def test_strict_keeps_only_marked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_claude_session(tmp_path, "marked-session")
    _write_claude_session(tmp_path, "unmarked-session")
    marked = tmp_path / "marked-sessions.jsonl"
    marked.write_text(
        json.dumps({"session_id": "marked-session", "marked_at": "x"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EVOMAP_PROXY_TRACE_FILE", str(tmp_path / "no-traces.jsonl"))
    base = {
        "runtimeSessions": 1,
        "homedir": str(tmp_path),
        "runtimeSessionDirs": [str(tmp_path / ".claude" / "projects")],
        "workspaceRoot": str(tmp_path),
        "markedSessionsFile": str(marked),
    }
    assert _discovered_ids(base) == ["marked-session"]

    with_unmarked = collect_runtime_session_inputs({**base, "includeUnmarked": 1})
    names = sorted(Path(f["path"]).name.replace(".jsonl", "") for f in with_unmarked["files"])
    assert names == ["marked-session", "unmarked-session"]

    strict = collect_runtime_session_inputs(base)
    assert strict["discovery"]["markGate"]["enforceMarked"] is True
    assert strict["discovery"]["markGate"]["excludedByMark"] == 1


def test_gateway_captured_excluded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_claude_session(tmp_path, "fresh-session")
    _write_claude_session(tmp_path, "already-captured")
    marked = tmp_path / "marked-sessions.jsonl"
    marked.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                {"session_id": "fresh-session", "marked_at": "x"},
                {"session_id": "already-captured", "marked_at": "x"},
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    trace = tmp_path / "proxy-traces.jsonl"
    trace.write_text(
        json.dumps(
            {
                "event": "llm_turn",
                "sessionId": hash_trace_value("already-captured", "session_id_sha256"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EVOMAP_PROXY_TRACE_FILE", str(trace))
    base = {
        "runtimeSessions": 1,
        "homedir": str(tmp_path),
        "runtimeSessionDirs": [str(tmp_path / ".claude" / "projects")],
        "workspaceRoot": str(tmp_path),
        "markedSessionsFile": str(marked),
    }
    assert _discovered_ids(base) == ["fresh-session"]

    with_gw = collect_runtime_session_inputs({**base, "includeGatewayCaptured": 1})
    names = sorted(Path(f["path"]).name.replace(".jsonl", "") for f in with_gw["files"])
    assert names == ["already-captured", "fresh-session"]

    strict = collect_runtime_session_inputs(base)
    assert strict["discovery"]["markGate"]["excludedByGateway"] == 1
    assert strict["discovery"]["markGate"]["gatewayCapturedCount"] == 1


def test_empty_registry_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_claude_session(tmp_path, "orphan-session")
    monkeypatch.setenv("EVOMAP_PROXY_TRACE_FILE", str(tmp_path / "no-traces.jsonl"))
    opts = {
        "runtimeSessions": 1,
        "homedir": str(tmp_path),
        "runtimeSessionDirs": [str(tmp_path / ".claude" / "projects")],
        "workspaceRoot": str(tmp_path),
        "markedSessionsFile": str(tmp_path / "does-not-exist.jsonl"),
    }
    assert _discovered_ids(opts) == []


def test_include_unmarked_reopens_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_claude_session(tmp_path, "a")
    _write_claude_session(tmp_path, "b")
    monkeypatch.setenv("EVOMAP_PROXY_TRACE_FILE", str(tmp_path / "no-traces.jsonl"))
    opts = {
        "runtimeSessions": 1,
        "homedir": str(tmp_path),
        "runtimeSessionDirs": [str(tmp_path / ".claude" / "projects")],
        "includeUnmarked": 1,
        "markedSessionsFile": str(tmp_path / "empty.jsonl"),
    }
    assert set(_discovered_ids(opts)) == {"a", "b"}
