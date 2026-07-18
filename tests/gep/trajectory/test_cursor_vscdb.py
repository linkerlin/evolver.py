"""Cursor state.vscdb adapter tests (Sprint 15.3 / FIX-4)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from evolver.gep.trajectory.cursor_vscdb import build_cursor_trajectories_from_vscdb
from evolver.gep.trajectory.inputs import read_trajectory_inputs_detailed


def _make_vscdb(tmp_path: Path, rows: list[tuple[str, object]]) -> Path:
    db_path = tmp_path / "state.vscdb"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value TEXT)")
    for key, value in rows:
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            (key, value if isinstance(value, str) else json.dumps(value)),
        )
    conn.commit()
    conn.close()
    return db_path


def test_inline_conversation_map(tmp_path: Path) -> None:
    composer_id = "comp-inline-1"
    composer = {
        "composerId": composer_id,
        "modelConfig": {"modelName": "claude-sonnet"},
        "fullConversationHeadersOnly": [{"bubbleId": "b1"}, {"bubbleId": "b2"}],
        "conversationMap": {
            "b1": {"bubbleId": "b1", "type": 1, "text": "Refactor the auth module"},
            "b2": {
                "bubbleId": "b2",
                "type": 2,
                "thinking": {"text": "I will read the file first."},
                "text": "On it.",
                "toolFormerData": {
                    "name": "read_file",
                    "toolCallId": "call-1",
                    "rawArgs": {"path": "auth.ts"},
                    "result": "file contents here",
                },
            },
        },
    }
    db_path = _make_vscdb(tmp_path, [(f"composerData:{composer_id}", composer)])
    res = read_trajectory_inputs_detailed(db_path)
    assert len(res["sessionTrajectories"]) == 1
    t = res["sessionTrajectories"][0]
    assert t.source_agent == "cursor"
    assert t.client_source == "cursor"
    assert t.session_id == composer_id
    assert t.session_model == "claude-sonnet"
    assert t.task == "Refactor the auth module"
    assert t.stats.has_tool_calls is True
    assert t.stats.tool_types.get("read_file") == 1
    blob = json.dumps([turn.__dict__ for turn in t.turns], default=str)
    assert "read the file first" in blob
    assert "file contents here" in blob


def test_separate_bubble_id_rows(tmp_path: Path) -> None:
    composer_id = "comp-bubbles-2"
    composer = {
        "composerId": composer_id,
        "fullConversationHeadersOnly": [{"bubbleId": "x1"}, {"bubbleId": "x2"}],
        "conversationMap": {},
    }
    rows = [
        (f"composerData:{composer_id}", composer),
        (f"bubbleId:{composer_id}:x1", {"bubbleId": "x1", "type": 1, "text": "Run the build"}),
        (
            f"bubbleId:{composer_id}:x2",
            {
                "bubbleId": "x2",
                "type": 2,
                "text": "Building now",
                "toolFormerData": {
                    "name": "run_terminal_cmd",
                    "params": {"command": "npm run build"},
                    "result": "build ok",
                },
            },
        ),
    ]
    db_path = _make_vscdb(tmp_path, rows)
    res = read_trajectory_inputs_detailed(db_path)
    assert len(res["sessionTrajectories"]) == 1
    t = res["sessionTrajectories"][0]
    assert t.task == "Run the build"
    assert t.stats.has_tool_calls is True
    assert t.stats.tool_types.get("run_terminal_cmd") == 1


def test_skips_empty_composers(tmp_path: Path) -> None:
    db_path = _make_vscdb(
        tmp_path,
        [("composerData:empty", {"composerId": "empty", "conversationMap": {}})],
    )
    sessions = build_cursor_trajectories_from_vscdb(db_path)
    assert sessions == []
