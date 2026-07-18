"""Runtime metadata: thinking_empty + system_prompt (Sprint 15.3 / FIX-7/8)."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.gep.trajectory.inputs import read_trajectory_inputs_detailed


def _write_claude(tmp_path: Path, records: list[dict]) -> Path:
    directory = tmp_path / ".claude" / "projects" / "proj"
    directory.mkdir(parents=True)
    file = directory / "claude-session.jsonl"
    file.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return file


def _write_codex(tmp_path: Path, records: list[dict]) -> Path:
    directory = tmp_path / ".codex" / "sessions"
    directory.mkdir(parents=True)
    file = directory / "rollout-2026-06-26.jsonl"
    file.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return file


def test_claude_empty_thinking_preserved(tmp_path: Path) -> None:
    file = _write_claude(
        tmp_path,
        [
            {"type": "user", "message": {"role": "user", "content": "Solve it"}},
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": ""},
                        {"type": "redacted_thinking", "data": "encrypted-blob"},
                        {"type": "text", "text": "Done."},
                    ],
                },
            },
        ],
    )
    res = read_trajectory_inputs_detailed(file)
    t = res["sessionTrajectories"][0]
    empty = [turn for turn in t.turns if turn.thinking_empty is True]
    assert empty, "empty thinking blocks must be preserved, not dropped"
    assert all(turn.reasoning is not None for turn in empty)


def test_codex_base_instructions_as_system_prompt(tmp_path: Path) -> None:
    file = _write_codex(
        tmp_path,
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "sess-codex",
                    "base_instructions": "You are a careful coding agent.",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "hi"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "hello"}],
                },
            },
        ],
    )
    res = read_trajectory_inputs_detailed(file)
    t = res["sessionTrajectories"][0]
    assert t.system_prompt == "You are a careful coding agent."


def test_claude_system_role_as_system_prompt(tmp_path: Path) -> None:
    file = _write_claude(
        tmp_path,
        [
            {
                "type": "system",
                "message": {"role": "system", "content": "Follow the repo conventions."},
            },
            {"type": "user", "message": {"role": "user", "content": "do x"}},
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "ok"}],
                },
            },
        ],
    )
    res = read_trajectory_inputs_detailed(file)
    t = res["sessionTrajectories"][0]
    assert t.system_prompt == "Follow the repo conventions."
