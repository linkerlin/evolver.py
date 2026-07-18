"""Gemini CLI session adapter (Slice 3b / FIX-3).

Reads ``~/.gemini/tmp/<project>/chats/session-*.{json,jsonl}``:

* **jsonl** — header line + per-message lines (``$set`` mutations skipped)
* **json** — single object with ``messages[]``
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
from evolver.gep.trajectory.sources import _finalise, _looks_like_failure, _model_provider

GEMINI_CLI_FILE_RE = re.compile(
    r"(^|[/\\])\.gemini[/\\]tmp[/\\][^/\\]+[/\\]chats[/\\]session-[^/\\]*\.jsonl?$",
    re.I,
)


def is_gemini_cli_path(path: str | Path) -> bool:
    return bool(GEMINI_CLI_FILE_RE.search(str(path).replace("\\", "/")))


def _safe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        return content["text"]
    return ""


def gemini_cli_message_records(chunk: str) -> list[dict[str, Any]]:
    text = (chunk or "").strip()
    if not text:
        return []
    whole = _safe_json(text)
    if isinstance(whole, dict):
        if isinstance(whole.get("messages"), list):
            return [m for m in whole["messages"] if isinstance(m, dict)]
        if whole.get("type"):
            return [whole]
    if isinstance(whole, list):
        return [r for r in whole if isinstance(r, dict) and r.get("type") and r.get("$set") is None]
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        obj = _safe_json(s)
        if not isinstance(obj, dict):
            continue
        if obj.get("$set") is not None:
            continue
        if not obj.get("type"):
            continue
        out.append(obj)
    return out


def _thought_text(thought: Any) -> str:
    if isinstance(thought, str):
        return thought
    if not isinstance(thought, dict):
        return ""
    subject = str(thought.get("subject") or "").strip()
    description = str(thought.get("description") or "").strip()
    if subject and description:
        return f"{subject}: {description}"
    return subject or description


def _tool_result_text(result: Any) -> str:
    if not isinstance(result, list):
        if result is None:
            return ""
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    parts: list[str] = []
    for entry in result:
        if not isinstance(entry, dict):
            continue
        fr = entry.get("functionResponse")
        if isinstance(fr, dict):
            resp = fr.get("response")
            if isinstance(resp, dict) and isinstance(resp.get("output"), str):
                parts.append(resp["output"])
            elif resp is not None:
                parts.append(
                    resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False)
                )
        else:
            parts.append(json.dumps(entry, ensure_ascii=False))
    return "\n".join(p for p in parts if p)


def build_gemini_cli_trajectory(  # noqa: PLR0912, PLR0915
    chunk: str, *, source_path: str = ""
) -> Trajectory:
    records = gemini_cli_message_records(chunk)
    session_id = ""
    task = ""
    turns: list[Turn] = []
    input_tokens = 0
    output_tokens = 0
    providers: list[str] = []
    has_test = False
    has_edit = False
    has_failure = False
    session_model = ""

    # Header session id from first jsonl line if present.
    for raw_line in (chunk or "").splitlines():
        obj = _safe_json(raw_line.strip())
        if isinstance(obj, dict) and obj.get("sessionId") and not obj.get("type"):
            session_id = str(obj["sessionId"])
            break
    whole = _safe_json((chunk or "").strip())
    if isinstance(whole, dict) and whole.get("sessionId"):
        session_id = str(whole["sessionId"])

    for msg in records:
        mtype = str(msg.get("type") or "")
        created = msg.get("timestamp") if isinstance(msg.get("timestamp"), str) else None
        model = str(msg.get("model") or "")
        if model and not session_model:
            session_model = model
        tokens = msg.get("tokens") if isinstance(msg.get("tokens"), dict) else {}
        msg_it = int(tokens.get("input") or 0) if tokens else 0
        msg_ot = int(tokens.get("output") or 0) if tokens else 0

        if mtype == "user":
            text = _content_text(msg.get("content"))
            if text and not task:
                task = text
            continue
        if mtype != "gemini":
            continue  # drop info / other

        usage_attached = False
        prov = _model_provider(model) or "google"
        if prov not in providers:
            providers.append(prov)

        def _take_usage(it: int = msg_it, ot: int = msg_ot) -> tuple[int, int]:
            nonlocal usage_attached, input_tokens, output_tokens
            if usage_attached:
                return 0, 0
            usage_attached = True
            input_tokens += it
            output_tokens += ot
            return it, ot

        for thought in msg.get("thoughts") or []:
            thought_text = _thought_text(thought)
            if not thought_text:
                continue
            uit, uot = _take_usage()
            turns.append(
                Turn(
                    provider=prov,
                    endpoint="gemini-cli",
                    model=model,
                    created_at=created,
                    reasoning=thought_text,
                    input_tokens=uit,
                    output_tokens=uot,
                )
            )

        text = _content_text(msg.get("content"))
        if text:
            uit, uot = _take_usage()
            turns.append(
                Turn(
                    provider=prov,
                    endpoint="gemini-cli",
                    model=model,
                    created_at=created,
                    input_tokens=uit,
                    output_tokens=uot,
                    response_body={"text": text},
                )
            )

        for call in msg.get("toolCalls") or []:
            if not isinstance(call, dict):
                continue
            name = str(call.get("name") or "")
            tool_id = str(call["id"]) if call.get("id") else None
            args = call.get("args")
            tc = ToolCall(name=name, id=tool_id, arguments=args, input=args)
            arg_text = ""
            if isinstance(args, dict):
                cmd = args.get("command") or args.get("cmd")
                arg_text = cmd if isinstance(cmd, str) else json.dumps(args)
            elif isinstance(args, str):
                arg_text = args
            if command_runs_tests(arg_text):
                has_test = True
            if is_code_edit(name, args):
                has_edit = True
            uit, uot = _take_usage()
            turns.append(
                Turn(
                    provider=prov,
                    endpoint="gemini-cli",
                    model=model,
                    created_at=created,
                    tool_calls=[tc],
                    input_tokens=uit,
                    output_tokens=uot,
                    response_body={"tool_name": name, "tool_use_id": tool_id},
                )
            )
            result_text = _tool_result_text(call.get("result"))
            is_error = str(call.get("status") or "").lower() == "error"
            if result_text or is_error:
                if is_error or _looks_like_failure(result_text):
                    has_failure = True
                turns.append(
                    Turn(
                        provider=prov,
                        endpoint="gemini-cli",
                        model=model,
                        created_at=created,
                        is_failure_correction=is_error or _looks_like_failure(result_text),
                        error=result_text if is_error else None,
                        response_body={
                            "tool_name": name,
                            "tool_use_id": tool_id,
                            "content": result_text,
                        },
                    )
                )

    if not session_id:
        session_id = Path(source_path).stem if source_path else "gemini-session"

    traj = _finalise(
        session_id=session_id,
        task=task,
        turns=turns,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        providers=providers or ["google"],
        has_test=has_test,
        has_edit=has_edit,
        has_failure=has_failure,
        source_agent="gemini-cli",
        source_path=source_path,
    )
    traj.client_source = "gemini-cli"
    traj.session_model = session_model or None
    return traj


def build_gemini_cli_trajectory_from_path(path: Path | str) -> Trajectory | None:
    p = Path(path)
    if not p.is_file() or not is_gemini_cli_path(p):
        return None
    return build_gemini_cli_trajectory(p.read_text(encoding="utf-8"), source_path=str(p))


__all__ = [
    "GEMINI_CLI_FILE_RE",
    "build_gemini_cli_trajectory",
    "build_gemini_cli_trajectory_from_path",
    "gemini_cli_message_records",
    "is_gemini_cli_path",
]
