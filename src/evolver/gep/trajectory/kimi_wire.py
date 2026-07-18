"""Kimi CLI wire.jsonl adapter (Slice 3b / FIX-5).

Path: ``~/.kimi/sessions/<workspaceHash>/<sessionId>/wire.jsonl``

Events: TurnBegin / ContentPart(think|text) / ToolCall / ToolResult.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from evolver.gep.trajectory.builder import (
    ToolCall,
    Trajectory,
    Turn,
    command_runs_tests,
    is_code_edit,
)
from evolver.gep.trajectory.sources import _finalise, _looks_like_failure

KIMI_WIRE_FILE_RE = re.compile(
    r"(^|[/\\])\.kimi[/\\]sessions[/\\][^/\\]+[/\\][^/\\]+[/\\]wire\.jsonl$",
    re.I,
)


def is_kimi_wire_path(path: str | Path) -> bool:
    return bool(KIMI_WIRE_FILE_RE.search(str(path).replace("\\", "/")))


def _safe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _user_input_text(user_input: Any) -> str:
    if isinstance(user_input, str):
        return user_input
    if isinstance(user_input, list):
        parts: list[str] = []
        for item in user_input:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return ""


def _parse_args(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return {"_raw": raw}
    return raw


def build_kimi_wire_trajectory(  # noqa: PLR0912, PLR0915
    chunk: str, *, source_path: str = ""
) -> Trajectory:
    task = ""
    turns: list[Turn] = []
    has_test = False
    has_edit = False
    has_failure = False

    for line in (chunk or "").splitlines():
        s = line.strip()
        if not s:
            continue
        obj = _safe_json(s)
        if not isinstance(obj, dict):
            continue
        if obj.get("type") == "metadata" or not isinstance(obj.get("message"), dict):
            continue
        message = obj["message"]
        mtype = message.get("type")
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        ts = obj.get("timestamp")
        created = str(ts) if ts is not None else None

        if mtype == "TurnBegin":
            text = _user_input_text(payload.get("user_input"))
            if text and not task:
                task = text
            continue

        if mtype == "ContentPart":
            if payload.get("type") == "think":
                think = payload.get("think") if isinstance(payload.get("think"), str) else ""
                if think:
                    turns.append(
                        Turn(
                            provider="kimi",
                            endpoint="kimi-cli",
                            created_at=created,
                            reasoning=think,
                        )
                    )
            else:
                text = payload.get("text") if isinstance(payload.get("text"), str) else ""
                if text:
                    turns.append(
                        Turn(
                            provider="kimi",
                            endpoint="kimi-cli",
                            created_at=created,
                            response_body={"text": text},
                        )
                    )
            continue

        if mtype == "ToolCall":
            fn = payload.get("function") if isinstance(payload.get("function"), dict) else {}
            name = str(fn.get("name") or payload.get("name") or "")
            tool_id = str(payload["id"]) if payload.get("id") else None
            args_raw = fn.get("arguments")
            args = _parse_args(args_raw)
            call = ToolCall(
                name=name,
                id=tool_id,
                arguments=args_raw,
                input=args,
                function={"name": name, "arguments": args_raw} if name else None,
            )
            arg_text = ""
            if isinstance(args, dict):
                cmd = args.get("command") or args.get("cmd") or args.get("path")
                arg_text = (
                    cmd if isinstance(cmd, str) else (args_raw if isinstance(args_raw, str) else "")
                )
            elif isinstance(args_raw, str):
                arg_text = args_raw
            if command_runs_tests(arg_text):
                has_test = True
            if is_code_edit(name, args):
                has_edit = True
            turns.append(
                Turn(
                    provider="kimi",
                    endpoint="kimi-cli",
                    created_at=created,
                    tool_calls=[call],
                    response_body={"tool_name": name, "tool_use_id": tool_id},
                )
            )
            continue

        if mtype == "ToolResult":
            ret = (
                payload.get("return_value") if isinstance(payload.get("return_value"), dict) else {}
            )
            output = ret.get("output")
            if not isinstance(output, str):
                output = json.dumps(output if output is not None else ret, ensure_ascii=False)
            tool_id = str(payload["tool_call_id"]) if payload.get("tool_call_id") else None
            is_error = ret.get("is_error") is True
            if is_error or _looks_like_failure(output):
                has_failure = True
            turns.append(
                Turn(
                    provider="kimi",
                    endpoint="kimi-cli",
                    created_at=created,
                    is_failure_correction=is_error or _looks_like_failure(output),
                    error=output if is_error else None,
                    response_body={
                        "tool_name": "ToolResult",
                        "tool_use_id": tool_id,
                        "content": output,
                    },
                )
            )

    session_id = "kimi-session"
    if source_path:
        # .../<hash>/<sessionId>/wire.jsonl
        parts = Path(source_path).parts
        if len(parts) >= 2 and parts[-1].lower() == "wire.jsonl":
            session_id = parts[-2]

    traj = _finalise(
        session_id=session_id,
        task=task,
        turns=turns,
        input_tokens=0,
        output_tokens=0,
        providers=["kimi"],
        has_test=has_test,
        has_edit=has_edit,
        has_failure=has_failure,
        source_agent="kimi",
        source_path=source_path,
    )
    traj.client_source = "kimi-cli"
    return traj


def build_kimi_wire_trajectory_from_path(path: Path | str) -> Trajectory | None:
    p = Path(path)
    if not p.is_file() or not is_kimi_wire_path(p):
        return None
    return build_kimi_wire_trajectory(p.read_text(encoding="utf-8"), source_path=str(p))


__all__ = [
    "KIMI_WIRE_FILE_RE",
    "build_kimi_wire_trajectory",
    "build_kimi_wire_trajectory_from_path",
    "is_kimi_wire_path",
]
