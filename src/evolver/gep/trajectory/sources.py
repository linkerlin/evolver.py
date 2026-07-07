"""Session-log trajectory sources (G10.1 slice 3a).

Parses non-proxy session transcripts into coding trajectories:

* **Codex rollout** JSONL (``.codex/sessions/rollout-*.jsonl``) —
  ``session_meta`` + ``response_item`` records (message / reasoning /
  function_call / function_call_output / custom_tool_call / tool_search_*).
* **Claude Code transcript** JSONL (``.claude/.../*.transcript.jsonl``) —
  ``user`` / ``assistant`` records with ``message.content`` blocks.

Each parser reuses the :mod:`builder` dataclasses and detects test execution,
code edits, and failure-correction from the tool calls / outputs.

Deferred to slice 3b: OpenAI generic messages, Cursor vscdb (SQLite), Gemini
CLI+Gateway, Kimi Wire, and streamed tool-argument reconstruction.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from evolver.gep.trajectory.builder import (
    SCHEMA,
    ToolCall,
    Trajectory,
    TrajectoryStats,
    Turn,
    _detect_languages,
    command_runs_tests,
    is_code_edit,
)

# Tool names whose invocation edits source code.
# (test/edit heuristics + extract_test_commands live in builder.py and are imported.)

# Output fragments that indicate a failure (exit code / failed / error).
_FAILURE_RE = re.compile(
    r"\b(exit\s+code:?\s*[1-9]|\b\d+\s+failed\b|failed|error|exception)\b", re.I
)


def _looks_like_failure(text: str | None) -> bool:
    return bool(text and _FAILURE_RE.search(text))


def _model_provider(model: str) -> str:
    m = (model or "").lower()
    if m.startswith("claude") or "anthropic" in m:
        return "anthropic"
    if m.startswith("gpt") or m.startswith("o1") or m.startswith("o3") or "openai" in m:
        return "openai"
    if m.startswith("gemini"):
        return "google"
    return ""


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            rec = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


# ---------------------------------------------------------------------------
# Source classification
# ---------------------------------------------------------------------------
def detect_source(records: list[dict[str, Any]], filename: str = "") -> str | None:
    """Classify a session JSONL: ``'codex'`` / ``'claude_code'`` / ``'generic-chat'`` / ``None``."""
    if not records:
        return None
    for rec in records:
        rtype = rec.get("type")
        payload = rec.get("payload")
        if rtype == "session_meta" or (rtype == "response_item" and isinstance(payload, dict)):
            return "codex"
        if rtype in ("user", "assistant") and isinstance(rec.get("message"), dict):
            return "claude_code"
    # Generic chat: top-level role-tagged messages (system/user/assistant/tool).
    if any(isinstance(r.get("role"), str) for r in records):
        return "generic-chat"
    if "transcript" in filename.lower():
        return "claude_code"
    return None


# ---------------------------------------------------------------------------
# Codex rollout
# ---------------------------------------------------------------------------
def build_codex_trajectory(records: list[dict[str, Any]], source_path: str = "") -> Trajectory:  # noqa: PLR0912, PLR0915
    session_id = ""
    task = ""
    turns: list[Turn] = []
    input_tokens = 0
    output_tokens = 0
    providers: list[str] = []
    has_test = False
    has_edit = False
    has_failure = False

    for rec in records:
        if rec.get("type") == "session_meta":
            payload = rec.get("payload") or {}
            session_id = str(payload.get("id") or session_id)
            continue
        if rec.get("type") != "response_item":
            continue
        payload = rec.get("payload") or {}
        ptype = payload.get("type")
        created = rec.get("timestamp")

        if ptype == "message" and payload.get("role") == "user":
            for block in payload.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "input_text" and not task:
                    task = str(block.get("text") or "")

        elif ptype == "reasoning":
            model = str(payload.get("model") or "")
            usage = payload.get("usage") or {}
            it = int(usage.get("input_tokens") or 0)
            ot = int(usage.get("output_tokens") or 0)
            input_tokens += it
            output_tokens += ot
            summary = payload.get("summary") or []
            reasoning = ""
            if isinstance(summary, list) and summary:
                reasoning = (
                    str(summary[0].get("text") or "") if isinstance(summary[0], dict) else ""
                )
            prov = _model_provider(model)
            if prov and prov not in providers:
                providers.append(prov)
            turns.append(
                Turn(
                    provider=prov,
                    endpoint="codex",
                    model=model,
                    created_at=created,
                    reasoning=reasoning or None,
                    encrypted_content=payload.get("encrypted_content"),
                    input_tokens=it,
                    output_tokens=ot,
                )
            )

        elif ptype in ("function_call", "custom_tool_call"):
            name = str(payload.get("name") or "")
            args = payload.get("arguments")
            inp = payload.get("input", args)
            call = ToolCall(
                name=name,
                id=payload.get("call_id") or payload.get("id"),
                arguments=args,
                input=inp,
            )
            cmd_text = ""
            if isinstance(args, str):
                cmd_text = args
            elif isinstance(inp, str):
                cmd_text = inp
            if command_runs_tests(cmd_text):
                has_test = True
            if is_code_edit(name, inp):
                has_edit = True
            turns.append(
                Turn(
                    provider=_model_provider(""),
                    endpoint="codex",
                    created_at=created,
                    tool_calls=[call],
                    response_body={"tool_name": name, "tool_use_id": call.id},
                )
            )

        elif ptype == "tool_search_call":
            query = payload.get("query")
            filters = payload.get("filters") or {}
            call = ToolCall(
                name="tool_search_call",
                id=payload.get("id"),
                input={"query": query, **filters} if query else filters,
            )
            turns.append(
                Turn(
                    provider="",
                    endpoint="codex",
                    created_at=created,
                    tool_calls=[call],
                    response_body={"tool_name": "tool_search_call", "tool_use_id": call.id},
                )
            )

        elif ptype in ("function_call_output", "tool_search_output"):
            output = payload.get("output")
            if ptype == "tool_search_output":
                output = payload.get("results")
            failed = _looks_like_failure(output if isinstance(output, str) else None)
            if failed:
                has_failure = True
            turns.append(
                Turn(
                    provider="",
                    endpoint="codex",
                    created_at=created,
                    is_failure_correction=failed,
                    error=output if isinstance(output, str) else None,
                    response_body={
                        "tool_name": ptype,
                        "tool_use_id": payload.get("call_id"),
                    },
                )
            )

    return _finalise(
        session_id=session_id or _fallback_session_id(source_path),
        task=task,
        turns=turns,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        providers=providers,
        has_test=has_test,
        has_edit=has_edit,
        has_failure=has_failure,
        source_agent="codex",
        source_path=source_path,
    )


# ---------------------------------------------------------------------------
# Claude Code transcript
# ---------------------------------------------------------------------------
def build_claude_code_trajectory(  # noqa: PLR0912, PLR0915
    records: list[dict[str, Any]], source_path: str = ""
) -> Trajectory:
    session_id = _fallback_session_id(source_path)
    task = ""
    turns: list[Turn] = []
    input_tokens = 0
    output_tokens = 0
    providers: list[str] = []
    has_test = False
    has_edit = False
    has_failure = False

    for rec in records:
        rtype = rec.get("type")
        message = rec.get("message") or {}
        content = message.get("content") if isinstance(message, dict) else None
        created = rec.get("timestamp")

        if rtype == "user" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and not task:
                    task = str(block.get("text") or "")
                elif block.get("type") == "tool_result":
                    inner = block.get("content")
                    failed = bool(block.get("is_error")) or _looks_like_failure(
                        inner if isinstance(inner, str) else None
                    )
                    if failed:
                        has_failure = True
                    turns.append(
                        Turn(
                            provider="anthropic",
                            endpoint="claude_code",
                            created_at=created,
                            is_failure_correction=failed,
                            error=inner if isinstance(inner, str) else None,
                            response_body={
                                "tool_name": "tool_result",
                                "tool_use_id": block.get("tool_use_id"),
                            },
                        )
                    )

        elif rtype == "assistant" and isinstance(message, dict):
            model = str(message.get("model") or "")
            usage = message.get("usage") or {}
            it = int(usage.get("input_tokens") or 0)
            ot = int(usage.get("output_tokens") or 0)
            input_tokens += it
            output_tokens += ot
            prov = _model_provider(model) or "anthropic"
            if prov not in providers:
                providers.append(prov)
            reasoning: str | None = None
            encrypted: str | None = None
            tool_calls: list[ToolCall] = []
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "thinking":
                        reasoning = block.get("thinking") or reasoning
                        encrypted = block.get("encrypted_signature") or encrypted
                    elif block.get("type") == "tool_use":
                        name = str(block.get("name") or "")
                        inp = block.get("input")
                        tool_calls.append(
                            ToolCall(name=name, id=block.get("id"), arguments=inp, input=inp)
                        )
                        cmd = inp.get("command") if isinstance(inp, dict) else inp
                        if command_runs_tests(str(cmd) if cmd is not None else ""):
                            has_test = True
                        if is_code_edit(name, inp):
                            has_edit = True
            turns.append(
                Turn(
                    provider=prov,
                    endpoint="claude_code",
                    model=model,
                    created_at=created,
                    reasoning=reasoning,
                    encrypted_content=encrypted,
                    input_tokens=it,
                    output_tokens=ot,
                    tool_calls=tool_calls,
                )
            )

    return _finalise(
        session_id=session_id,
        task=task,
        turns=turns,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        providers=providers,
        has_test=has_test,
        has_edit=has_edit,
        has_failure=has_failure,
        source_agent="claude_code",
        source_path=source_path,
    )


# ---------------------------------------------------------------------------
# Generic OpenAI messages JSONL (top-level role-tagged messages)
# ---------------------------------------------------------------------------
def build_generic_chat_trajectory(  # noqa: PLR0912, PLR0915
    records: list[dict[str, Any]], source_path: str = ""
) -> Trajectory:
    session_id = _fallback_session_id(source_path)
    task = ""
    turns: list[Turn] = []
    input_tokens = 0
    output_tokens = 0
    has_test = False
    has_edit = False
    has_failure = False

    for rec in records:
        role = rec.get("role")
        if role == "system":
            continue
        if role == "user":
            content = rec.get("content")
            if isinstance(content, str) and not task:
                task = content
            continue
        if role == "tool":
            content = rec.get("content")
            failed = _looks_like_failure(content if isinstance(content, str) else None)
            if failed:
                has_failure = True
            turns.append(
                Turn(
                    provider="openai",
                    endpoint="generic-chat",
                    is_failure_correction=failed,
                    error=content if isinstance(content, str) else None,
                    response_body={
                        "tool_name": "tool",
                        "tool_use_id": rec.get("tool_call_id"),
                    },
                )
            )
            continue
        if role != "assistant":
            continue

        model = str(rec.get("model") or "")
        usage = rec.get("usage") or {}
        it = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        ot = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        input_tokens += it
        output_tokens += ot
        reasoning: str | None = None
        signature: str | None = None
        tool_calls: list[ToolCall] = []
        content = rec.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "thinking":
                    reasoning = block.get("thinking") or reasoning
                    signature = block.get("signature") or signature
        for tc in rec.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            name = str(fn.get("name") or "")
            args_str = fn.get("arguments")
            try:
                inp = json.loads(args_str) if isinstance(args_str, str) else args_str
            except ValueError:
                inp = {"_raw": args_str}
            call = ToolCall(
                name=name,
                id=tc.get("id"),
                arguments=args_str,
                input=inp,
                function={"name": name, "arguments": args_str},
            )
            tool_calls.append(call)
            cmd = inp.get("cmd") if isinstance(inp, dict) else None
            arg_text = cmd if isinstance(cmd, str) else (args_str or "")
            if command_runs_tests(arg_text):
                has_test = True
            if is_code_edit(name, inp):
                has_edit = True
        turns.append(
            Turn(
                provider="openai",
                endpoint="generic-chat",
                model=model,
                reasoning=reasoning,
                reasoning_signature=signature,
                input_tokens=it,
                output_tokens=ot,
                tool_calls=tool_calls,
            )
        )

    return _finalise(
        session_id=session_id,
        task=task,
        turns=turns,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        providers=["openai"],
        has_test=has_test,
        has_edit=has_edit,
        has_failure=has_failure,
        source_agent="generic-chat",
        source_path=source_path,
    )


# ---------------------------------------------------------------------------
# Shared finalisation
# ---------------------------------------------------------------------------
def _fallback_session_id(source_path: str) -> str:
    name = Path(source_path).stem if source_path else ""
    return name or "session"


def _finalise(
    *,
    session_id: str,
    task: str,
    turns: list[Turn],
    input_tokens: int,
    output_tokens: int,
    providers: list[str],
    has_test: bool,
    has_edit: bool,
    has_failure: bool,
    source_agent: str,
    source_path: str,
) -> Trajectory:
    tool_types: dict[str, int] = {}
    actual = 0
    test_commands: list[str] = []
    for turn in turns:
        for call in turn.tool_calls:
            if call.declared or call.name in ("function_call_output", "tool_result", "tool"):
                continue
            actual += 1
            tool_types[call.name] = tool_types.get(call.name, 0) + 1
            inp = call.input
            arg_text = ""
            if isinstance(inp, dict):
                cmd = inp.get("command") or inp.get("cmd")
                if isinstance(cmd, str):
                    arg_text = cmd
            elif isinstance(inp, str):
                arg_text = inp
            if command_runs_tests(arg_text):
                test_commands.append(arg_text)
    languages = _detect_languages(task)
    stats = TrajectoryStats(
        turns=len(turns),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        has_tool_calls=actual > 0,
        tool_call_count=actual,
        has_failure_correction=has_failure,
        has_test_execution=has_test or bool(test_commands),
        has_code_edit=has_edit,
        tool_types=tool_types,
        test_commands=test_commands,
    )
    return Trajectory(
        session_id=session_id,
        task=task,
        languages=languages,
        providers=providers,
        turns=turns,
        stats=stats,
        source_kind="runtime_session",
        source_agent=source_agent,
        source_path=source_path,
    )


def build_trajectory_from_session_log(path: Path | str) -> Trajectory | None:
    """Classify and parse a session-log JSONL into a trajectory (or None)."""
    p = Path(path)
    records = _read_jsonl(p)
    source = detect_source(records, p.name)
    if source == "codex":
        return build_codex_trajectory(records, source_path=str(p))
    if source == "claude_code":
        return build_claude_code_trajectory(records, source_path=str(p))
    if source == "generic-chat":
        return build_generic_chat_trajectory(records, source_path=str(p))
    return None


# Re-export schema for convenience.
__all__ = [
    "SCHEMA",
    "build_claude_code_trajectory",
    "build_codex_trajectory",
    "build_generic_chat_trajectory",
    "build_trajectory_from_session_log",
    "detect_source",
]
