"""Cursor state.vscdb trajectory adapter (Slice 3b / FIX-4).

Reads conversations from Cursor's SQLite ``state.vscdb`` (``cursorDiskKV``
table). Supports both storage layouts:

1. Bubbles inlined under ``composerData.conversationMap``
2. Bubbles as separate ``bubbleId:<composerId>:<bubbleId>`` rows
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from evolver.gep.trajectory.builder import (
    ToolCall,
    Trajectory,
    Turn,
    command_runs_tests,
    is_code_edit,
)
from evolver.gep.trajectory.sources import _finalise, _model_provider

CURSOR_VSCDB_FILE_RE = re.compile(r"(^|[/\\])state\.vscdb$", re.I)


def is_cursor_vscdb_path(path: str | Path) -> bool:
    return bool(CURSOR_VSCDB_FILE_RE.search(str(path).replace("\\", "/")))


def _parse_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return None


def _bubble_to_turns(bubble: dict[str, Any]) -> list[Turn]:
    """Map a Cursor bubble into one or more trajectory turns."""
    btype = bubble.get("type")
    if btype not in (1, 2):
        return []
    created = bubble.get("createdAt") or bubble.get("timestamp")
    turns: list[Turn] = []

    if btype == 1:  # user — task is harvested elsewhere; no turn required
        return []

    # assistant (type 2)
    thinking_obj = bubble.get("thinking")
    thinking = ""
    if isinstance(thinking_obj, dict):
        thinking = str(thinking_obj.get("text") or "")
    elif isinstance(thinking_obj, str):
        thinking = thinking_obj

    text = bubble.get("text") if isinstance(bubble.get("text"), str) else ""
    if not text and isinstance(bubble.get("richText"), str):
        text = bubble["richText"]

    tool = bubble.get("toolFormerData") if isinstance(bubble.get("toolFormerData"), dict) else None
    tool_calls: list[ToolCall] = []
    result_text: str | None = None
    tool_name = ""
    tool_id: str | None = None
    if tool:
        raw_args = tool["rawArgs"] if "rawArgs" in tool else tool.get("params")
        parsed_args = _parse_json(raw_args)
        if parsed_args is None:
            parsed_args = raw_args
        tool_name = str(tool.get("name") or tool.get("tool") or "unknown")
        tool_id = (
            str(tool["toolCallId"])
            if tool.get("toolCallId")
            else (str(tool["id"]) if tool.get("id") else None)
        )
        tool_calls.append(
            ToolCall(name=tool_name, id=tool_id, arguments=raw_args, input=parsed_args)
        )
        if "result" in tool:
            result_val = _parse_json(tool["result"])
            if result_val is None:
                result_val = tool["result"]
            result_text = (
                result_val
                if isinstance(result_val, str)
                else json.dumps(result_val, ensure_ascii=False)
            )

    if thinking or text or tool_calls:
        turns.append(
            Turn(
                provider="cursor",
                endpoint="cursor",
                created_at=str(created) if created else None,
                reasoning=thinking or None,
                tool_calls=tool_calls,
                response_body={"text": text} if text else {},
            )
        )
    if result_text is not None:
        turns.append(
            Turn(
                provider="cursor",
                endpoint="cursor",
                created_at=str(created) if created else None,
                response_body={
                    "tool_name": tool_name or "tool_result",
                    "tool_use_id": tool_id,
                    "content": result_text,
                },
                error=None,
            )
        )
        # Keep result text discoverable via JSON.stringify of turns.
        turns[-1].response_body["result"] = result_text
    return turns


def _ordered_bubble_ids(composer: dict[str, Any]) -> list[str]:
    headers = composer.get("fullConversationHeadersOnly")
    if not isinstance(headers, list):
        return []
    ids: list[str] = []
    for h in headers:
        if isinstance(h, dict):
            bid = h.get("bubbleId") or h.get("id")
            if isinstance(bid, str) and bid:
                ids.append(bid)
        elif isinstance(h, str) and h:
            ids.append(h)
    return ids


def _composer_task(bubbles: list[dict[str, Any]]) -> str:
    for bubble in bubbles:
        if bubble.get("type") == 1:
            text = bubble.get("text")
            if isinstance(text, str) and text.strip():
                return text
            rich = bubble.get("richText")
            if isinstance(rich, str) and rich.strip():
                return rich
    return ""


def build_cursor_trajectory_from_composer(  # noqa: PLR0912
    composer: dict[str, Any],
    *,
    bubble_lookup: dict[str, dict[str, Any]] | None = None,
    source_path: str = "",
) -> Trajectory | None:
    """Build one trajectory from a Cursor composer envelope + optional bubble rows."""
    cmap = (
        composer.get("conversationMap") if isinstance(composer.get("conversationMap"), dict) else {}
    )
    ordered = _ordered_bubble_ids(composer)
    bubble_ids = ordered or list(cmap.keys())
    bubbles: list[dict[str, Any]] = []
    for bid in bubble_ids:
        bubble = cmap.get(bid)
        if bubble is None and bubble_lookup is not None:
            bubble = bubble_lookup.get(bid)
        if isinstance(bubble, dict):
            bubbles.append(bubble)
    if not bubbles and isinstance(cmap, dict):
        bubbles = [b for b in cmap.values() if isinstance(b, dict)]
    if not bubbles:
        return None

    turns: list[Turn] = []
    has_test = False
    has_edit = False
    has_failure = False
    for bubble in bubbles:
        for turn in _bubble_to_turns(bubble):
            for call in turn.tool_calls:
                arg_text = ""
                inp = call.input
                if isinstance(inp, dict):
                    cmd = inp.get("command") or inp.get("cmd")
                    arg_text = cmd if isinstance(cmd, str) else json.dumps(inp)
                elif isinstance(inp, str):
                    arg_text = inp
                if command_runs_tests(arg_text):
                    has_test = True
                if is_code_edit(call.name, inp):
                    has_edit = True
            turns.append(turn)

    if not turns and not _composer_task(bubbles):
        return None
    # User-only composers still count if there is recoverable text/tools.
    if not turns and not any(b.get("type") in (1, 2) for b in bubbles):
        return None
    # Need at least one non-user recoverable piece, or skip empty composers.
    if not turns:
        # User message only — still emit a minimal trajectory with task.
        pass

    model_cfg = composer.get("modelConfig") if isinstance(composer.get("modelConfig"), dict) else {}
    model = str(
        model_cfg.get("modelName") or model_cfg.get("model") or model_cfg.get("name") or ""
    ) or str(composer.get("model") or composer.get("modelName") or "")
    session_id = str(composer.get("composerId") or "cursor-session")
    task = _composer_task(bubbles)
    traj = _finalise(
        session_id=session_id,
        task=task,
        turns=turns,
        input_tokens=0,
        output_tokens=0,
        providers=[_model_provider(model) or "cursor"],
        has_test=has_test,
        has_edit=has_edit,
        has_failure=has_failure,
        source_agent="cursor",
        source_path=source_path,
    )
    traj.client_source = "cursor"
    traj.session_model = model or None
    return traj


def build_cursor_trajectories_from_vscdb(  # noqa: PLR0912
    db_path: Path | str,
) -> list[Trajectory]:
    """Open *db_path* (state.vscdb) and return trajectories for every composer."""
    path = Path(db_path)
    if not path.is_file():
        return []
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        try:
            conn = sqlite3.connect(str(path))
        except sqlite3.Error:
            return []
    sessions: list[Trajectory] = []
    try:
        cur = conn.cursor()
        tables = {
            row[0]
            for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "cursorDiskKV" not in tables:
            return []

        bubble_by_composer: dict[str, dict[str, dict[str, Any]]] = {}
        for key, value in cur.execute(
            "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'"
        ).fetchall():
            parts = str(key).split(":")
            if len(parts) < 3:
                continue
            composer_id = parts[1]
            bubble_id = ":".join(parts[2:])
            parsed = _parse_json(value)
            if not isinstance(parsed, dict):
                continue
            bubble_by_composer.setdefault(composer_id, {})[bubble_id] = parsed

        for key, value in cur.execute(
            "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'"
        ).fetchall():
            composer = _parse_json(value)
            if not isinstance(composer, dict):
                continue
            if not composer.get("composerId"):
                composer["composerId"] = str(key).removeprefix("composerData:")
            cid = str(composer.get("composerId") or "")
            lookup = bubble_by_composer.get(cid)
            traj = build_cursor_trajectory_from_composer(
                composer,
                bubble_lookup=lookup,
                source_path=str(path),
            )
            if traj is not None and (traj.turns or traj.task):
                # Skip composers with no recoverable content.
                if not traj.turns and not traj.task:
                    continue
                # Empty map + no bubbles → no turns and empty task already filtered.
                if not traj.turns and not traj.stats.has_tool_calls and not traj.task:
                    continue
                sessions.append(traj)
    except sqlite3.Error:
        return sessions
    finally:
        conn.close()
    return sessions


__all__ = [
    "CURSOR_VSCDB_FILE_RE",
    "build_cursor_trajectories_from_vscdb",
    "build_cursor_trajectory_from_composer",
    "is_cursor_vscdb_path",
]
