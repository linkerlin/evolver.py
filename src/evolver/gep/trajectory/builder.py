"""Trajectory builder — group proxy trace rows into coding trajectories.

Behaviour-equivalent port of ``evolver/src/gep/trajectoryExport.js`` (the
``buildTrajectories`` / ``buildTrajectoryFromRows`` core). This is the
foundation slice (G10.1) of the multi-source trajectory export:

* proxy-trace rows → session-level trajectories (grouping, turn extraction,
  tool-call extraction across Anthropic / OpenAI Responses / Chat Completions,
  provider normalisation, language detection, failure-correction marking,
  stats aggregation).

Deferred to slice 2: encrypted-row decryption (``readTraceRowsDetailed``), the
non-proxy session-log sources (Codex rollout / Claude Code transcript / OpenAI
generic / Cursor vscdb / Gemini CLI+Gateway / Kimi Wire), and streamed
tool-argument reconstruction.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

SCHEMA: str = "evomap.coding_trajectory.v1"

# Bedrock hosts Anthropic models under the aws-bedrock upstream; normalise both
# the upstream alias and an explicit provider to the canonical taxonomy.
_PROVIDER_ALIASES: dict[str, str] = {
    "aws-bedrock": "aws-bedrock-anthropic",
    "bedrock": "aws-bedrock-anthropic",
}

# Language hints: keyword in task text OR tool/build command → language.
_LANGUAGE_KEYWORDS: list[tuple[str, re.Pattern[str]]] = [
    ("typescript", re.compile(r"\b(typescript|tsx|tsc|pnpm)\b|\.tsx?\b", re.I)),
    ("javascript", re.compile(r"\b(javascript|jsx|npm|node)\b|\.jsx?\b", re.I)),
    ("python", re.compile(r"\b(python|pytest|pip|mypy|ruff|uv)\b|\.py\b", re.I)),
    ("rust", re.compile(r"\b(rust|cargo)\b|\.rs\b", re.I)),
    ("java", re.compile(r"\b(java|maven|gradle)\b|\.java\b", re.I)),
    ("ruby", re.compile(r"\b(ruby|bundler)\b|\.rb\b", re.I)),
    (
        "go",
        re.compile(r"\b(golang|go\s+(?:test|parser|program|module|routine|lang))\b|\.go\b", re.I),
    ),
    ("csharp", re.compile(r"\b(csharp|c#|dotnet|nuget)\b|\.cs\b", re.I)),
    ("cpp", re.compile(r"\b(c\+\+|cpp)\b|\.(?:cpp|cc|cxx)\b", re.I)),
    ("c", re.compile(r"\b(?:gcc|cmake)\b|\.c\b", re.I)),
]

# Shared tool-call semantics for test/edit detection (used by builder + sources).
_TEST_CMD_RE = re.compile(
    r"\b(pytest|jest|vitest|mocha|rspec|nunit|"
    r"(?:cargo|go|npm|pnpm|yarn|mvn|gradle|dotnet)\s+test|node\s+--test)\b",
    re.I,
)
_CODE_EDIT_TOOLS: frozenset[str] = frozenset(
    {
        "apply_patch",
        "str_replace_editor",
        "edit",
        "write",
        "replace_in_file",
        "multiedit",
        "create_file",
        "write_file",
    }
)
_PATCH_MARKER_RE = re.compile(r"\*\*\*\s*(Begin Patch|Add File|End Patch|Update File|Delete File)")


def command_runs_tests(text: str) -> bool:
    """True if *text* (a tool command/arguments) invokes a test runner."""
    return bool(text and _TEST_CMD_RE.search(text))


def is_code_edit(name: str, input_value: Any) -> bool:
    """True if the tool invocation edits source code.

    Matched by tool name (apply_patch / str_replace_editor / …), by patch
    markers in the input, or — for generic shells (e.g. ``Bash``) — by patch
    markers / edit-tool names embedded in a ``command`` field.
    """
    if name in _CODE_EDIT_TOOLS:
        return True
    text = ""
    if isinstance(input_value, dict):
        cmd = input_value.get("command") or input_value.get("cmd")
        if isinstance(cmd, str):
            text = cmd
    elif isinstance(input_value, str):
        text = input_value
    if text:
        if _PATCH_MARKER_RE.search(text):
            return True
        if any(tool in text for tool in _CODE_EDIT_TOOLS):
            return True
    return False


@dataclass
class ToolCall:
    name: str
    arguments: Any = None
    output: Any = None
    failed: bool = False
    declared: bool = False
    input: Any = None
    id: str | None = None
    function: dict[str, Any] | None = None


@dataclass
class Turn:
    provider: str
    endpoint: str
    model: str = ""
    status: int | None = None
    response_id: str | None = None
    previous_response_id: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    is_failure_correction: bool = False
    created_at: str | None = None
    request_body: dict[str, Any] = field(default_factory=dict)
    response_body: dict[str, Any] = field(default_factory=dict)
    reasoning: str | None = None
    encrypted_content: str | None = None
    reasoning_signature: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


@dataclass
class TrajectoryStats:
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    has_tool_calls: bool = False
    tool_call_count: int = 0
    has_failure_correction: bool = False
    has_test_execution: bool = False
    has_code_edit: bool = False
    tool_types: dict[str, int] = field(default_factory=dict)
    test_commands: list[str] = field(default_factory=list)


@dataclass
class Trajectory:
    session_id: str
    task: str = ""
    schema: str = SCHEMA
    languages: list[str] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    stats: TrajectoryStats = field(default_factory=TrajectoryStats)
    source_kind: str | None = None
    source_agent: str | None = None
    source_path: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_provider(row: dict[str, Any]) -> str:
    raw = row.get("upstream") or row.get("provider") or ""
    return _PROVIDER_ALIASES.get(str(raw), str(raw)) if raw else ""


def _row_endpoint(row: dict[str, Any]) -> str:
    return str(row.get("path") or row.get("endpoint") or "")


def _parse_body(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _detect_languages(text: str) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    for lang, pattern in _LANGUAGE_KEYWORDS:
        if pattern.search(text) and lang not in found:
            found.append(lang)
    return found


def _user_text(messages: list[Any]) -> str:
    """Concatenate user-role message text from a messages array."""
    parts: list[str] = []
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif isinstance(block, str):
                    parts.append(block)
    return " ".join(parts)


def _extract_task(row: dict[str, Any], request: dict[str, Any]) -> str:
    path = _row_endpoint(row)
    if "/responses" in path:
        inp = request.get("input")
        if isinstance(inp, str):
            return inp
        if isinstance(inp, list):
            return _user_text([m for m in inp if isinstance(m, dict) and m.get("role")])
        instr = request.get("instructions")
        if isinstance(instr, str):
            return instr
    messages = request.get("messages")
    if isinstance(messages, list):
        text = _user_text(messages)
        if text:
            return text
    return ""


def _declared_tools(request: dict[str, Any]) -> list[ToolCall]:
    """Declared tool definitions (request ``tools``): listed but not invoked."""
    declared: list[ToolCall] = []
    for tool in request.get("tools", []) or []:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name") or (tool.get("function") or {}).get("name")
        if name:
            declared.append(ToolCall(name=str(name), declared=True))
    return declared


def _is_valid_json(text: str) -> bool:
    if not text:
        return False
    try:
        json.loads(text)
        return True
    except (ValueError, TypeError):
        return False


def _extract_streamed_openai_chat_tool_calls(response: dict[str, Any]) -> list[ToolCall]:  # noqa: PLR0912
    """Reconstruct OpenAI Chat tool calls from streamed argument deltas.

    Each event carries ``choices[].delta.tool_calls[]`` keyed by ``index``; the
    first delta holds ``id``/``name`` + the opening arguments fragment, later
    deltas append arguments fragments. A fragment that is itself valid JSON is
    a full snapshot and *replaces* the accumulator (dedup) rather than appending.
    """
    acc: dict[Any, dict[str, Any]] = {}
    order: list[Any] = []
    for ev in response.get("events") or []:
        for choice in ev.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            for tc in (choice.get("delta") or {}).get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                idx = tc.get("index", 0)
                fn = tc.get("function") or {}
                frag = fn.get("arguments")
                if idx not in acc:
                    acc[idx] = {"name": fn.get("name"), "id": tc.get("id"), "args": ""}
                    order.append(idx)
                if fn.get("name"):
                    acc[idx]["name"] = fn["name"]
                if tc.get("id"):
                    acc[idx]["id"] = tc["id"]
                if frag:
                    # Full-snapshot dedup: a standalone-valid fragment replaces
                    # a partial accumulator instead of producing invalid JSON.
                    if (
                        _is_valid_json(frag)
                        and acc[idx]["args"]
                        and not _is_valid_json(acc[idx]["args"])
                    ):
                        acc[idx]["args"] = frag
                    else:
                        acc[idx]["args"] += frag
    calls: list[ToolCall] = []
    for idx in order:
        a = acc[idx]
        args_str = a["args"]
        try:
            inp = json.loads(args_str) if args_str else {}
        except ValueError:
            inp = {"_raw": args_str}
        fn_obj = {"name": a["name"], "arguments": args_str}
        calls.append(
            ToolCall(
                name=str(a["name"] or ""),
                id=a["id"],
                arguments=args_str,
                input=inp,
                function=fn_obj,
            )
        )
    return calls


def _extract_streamed_openai_responses_tool_calls(response: dict[str, Any]) -> list[ToolCall]:
    """Reconstruct OpenAI Responses function calls from streamed argument deltas.

    Events: ``response.output_item.added`` (starts a function_call), successive
    ``response.function_call_arguments.delta`` (append), and
    ``response.function_call_arguments.done`` (final arguments, overrides the
    accumulated deltas). Grouped by ``output_index``.
    """
    items: dict[Any, dict[str, Any]] = {}
    order: list[Any] = []
    for ev in response.get("events") or []:
        if not isinstance(ev, dict):
            continue
        etype = ev.get("type")
        oidx = ev.get("output_index", 0)
        if etype == "response.output_item.added":
            item = ev.get("item") or {}
            if item.get("type") == "function_call":
                items[oidx] = {
                    "name": item.get("name"),
                    "call_id": item.get("call_id"),
                    "id": item.get("id"),
                    "args": item.get("arguments") or "",
                }
                order.append(oidx)
        elif etype == "response.function_call_arguments.delta":
            if oidx in items:
                items[oidx]["args"] = (items[oidx]["args"] or "") + (ev.get("delta") or "")
        elif etype == "response.function_call_arguments.done":
            if oidx in items and ev.get("arguments"):
                items[oidx]["args"] = ev["arguments"]
    calls: list[ToolCall] = []
    for oidx in order:
        it = items[oidx]
        args_str = it["args"]
        try:
            inp = json.loads(args_str) if args_str else {}
        except ValueError:
            inp = {"_raw": args_str}
        calls.append(
            ToolCall(
                name=str(it["name"] or ""),
                id=it["call_id"] or it["id"],
                arguments=args_str,
                input=inp,
            )
        )
    return calls


def _extract_streamed_anthropic_tool_calls(response: dict[str, Any]) -> list[ToolCall]:
    """Reconstruct Anthropic tool calls from streamed ``input_json_delta`` events.

    Streamed responses carry ``reconstructed_stream.events``: a
    ``content_block_start`` (tool_use, with name/id) followed by
    ``content_block_delta`` (``input_json_delta.partial_json``) fragments that
    must be concatenated per block index, then JSON-parsed into the tool input.
    """
    events = response.get("events") or []
    blocks: dict[Any, dict[str, Any]] = {}
    order: list[Any] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        etype = ev.get("type")
        if etype == "content_block_start":
            cb = ev.get("content_block") or {}
            if cb.get("type") == "tool_use":
                idx = ev.get("index")
                blocks[idx] = {"name": cb.get("name"), "id": cb.get("id"), "partials": []}
                order.append(idx)
        elif etype == "content_block_delta":
            idx = ev.get("index")
            delta = ev.get("delta") or {}
            if idx in blocks and delta.get("type") == "input_json_delta":
                blocks[idx]["partials"].append(delta.get("partial_json") or "")
    calls: list[ToolCall] = []
    for idx in order:
        block = blocks[idx]
        raw = "".join(block["partials"])
        try:
            inp = json.loads(raw) if raw else {}
        except ValueError:
            inp = {"_raw": raw}
        calls.append(ToolCall(name=str(block["name"]), id=block["id"], arguments=inp, input=inp))
    return calls


def _extract_tool_calls(row: dict[str, Any]) -> list[ToolCall]:  # noqa: PLR0912, PLR0915
    """Extract tool calls from request + response across the three API shapes.

    Declared tool definitions come first (``declared=True``); actual invocations
    follow (``declared=False``). Only actual invocations count toward stats.
    """
    request = _parse_body(row.get("requestBody"))
    response = _parse_body(row.get("responseBody"))
    path = _row_endpoint(row)
    actual: list[ToolCall] = []

    # Streamed responses carry reconstructed SSE events instead of a plain body.
    if response.get("reconstructed_stream") and (row.get("isStream") or response.get("events")):
        if "/chat" in path:
            actual = _extract_streamed_openai_chat_tool_calls(response)
        elif "/responses" in path:
            actual = _extract_streamed_openai_responses_tool_calls(response)
        else:
            actual = _extract_streamed_anthropic_tool_calls(response)
        return _declared_tools(request) + actual

    if "/responses" in path:
        # OpenAI Responses: function_call items in request.input + response.output.
        inp = request.get("input")
        if isinstance(inp, list):
            for item in inp:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "function_call" and item.get("name"):
                    actual.append(ToolCall(name=str(item["name"]), arguments=item.get("arguments")))
                elif item.get("type") == "function_call_output":
                    out = item.get("output")
                    failed = isinstance(out, str) and bool(
                        re.search(
                            r"\b(failed|error|exit(?:ed)?(?:\s+with)?(?:\s+code)?\s+[1-9])\b",
                            out,
                            re.I,
                        )
                    )
                    actual.append(ToolCall(name="function_call_output", output=out, failed=failed))
        for item in response.get("output", []) or []:
            if isinstance(item, dict) and item.get("type") == "function_call" and item.get("name"):
                actual.append(ToolCall(name=str(item["name"]), arguments=item.get("arguments")))

    elif "/chat" in path:
        # OpenAI Chat Completions: response.choices[].message.tool_calls.
        for choice in response.get("choices", []) or []:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message") or {}
            for tc in message.get("tool_calls", []) or []:
                if isinstance(tc, dict) and tc.get("function"):
                    fn = tc["function"]
                    if isinstance(fn, dict) and fn.get("name"):
                        actual.append(ToolCall(name=str(fn["name"]), arguments=fn.get("arguments")))

    else:
        # Anthropic /v1/messages: tool_use content blocks, deduped by id
        # (the request echoes the prior assistant tool_use; the response carries
        # the new one — same id appears once).
        seen_ids: set[str] = set()
        sources: list[Any] = []
        messages = request.get("messages")
        if isinstance(messages, list):
            sources.extend(messages)
        content = response.get("content")
        if isinstance(content, list):
            sources.append({"content": content})
        for src in sources:
            if not isinstance(src, dict):
                continue
            blocks = src.get("content")
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                if not block.get("name"):
                    continue
                tid = block.get("id")
                if tid:
                    if tid in seen_ids:
                        continue
                    seen_ids.add(tid)
                actual.append(ToolCall(name=str(block["name"]), arguments=block.get("input")))

    return _declared_tools(request) + actual


def _row_is_failure(row: dict[str, Any]) -> bool:
    status = row.get("status")
    if isinstance(status, int) and status >= 400:
        return True
    if row.get("errorMessage") or row.get("error"):
        return True
    response = _parse_body(row.get("responseBody"))
    return isinstance(response.get("error"), dict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_trajectory_from_rows(session_id: str, rows: list[dict[str, Any]]) -> Trajectory:  # noqa: PLR0912
    """Build a single coding trajectory for *session_id* from its trace *rows*."""
    session_rows = [
        r for r in rows if r.get("sessionId") == session_id or r.get("session_id") == session_id
    ]
    if not session_rows:
        session_rows = list(rows)

    turns: list[Turn] = []
    providers_seen: list[str] = []
    languages_seen: list[str] = []
    input_tokens = 0
    output_tokens = 0
    task = ""

    for row in session_rows:
        request = _parse_body(row.get("requestBody"))
        response = _parse_body(row.get("responseBody"))
        provider = _row_provider(row)
        if provider and provider not in providers_seen:
            providers_seen.append(provider)
        tool_calls = _extract_tool_calls(row)
        is_failure = _row_is_failure(row)
        turn = Turn(
            provider=provider,
            endpoint=_row_endpoint(row),
            model=str(row.get("model") or ""),
            status=row.get("status") if isinstance(row.get("status"), int) else None,
            response_id=row.get("responseId") or row.get("response_id"),
            previous_response_id=row.get("previousResponseId") or row.get("previous_response_id"),
            tool_calls=tool_calls,
            is_failure_correction=is_failure,
            created_at=row.get("createdAtIso") or row.get("created_at_iso"),
            request_body=request,
            response_body=response,
        )
        turns.append(turn)

        if not task:
            task = _extract_task(row, request)
        for lang in _detect_languages(task):
            if lang not in languages_seen:
                languages_seen.append(lang)
        input_tokens += int(row.get("input_tokens") or row.get("inputTokens") or 0)
        output_tokens += int(row.get("output_tokens") or row.get("outputTokens") or 0)

    # Stats count only actual invocations (declared tools do not count).
    tool_types: dict[str, int] = {}
    actual_call_count = 0
    has_test = False
    has_edit = False
    test_commands: list[str] = []
    for turn in turns:
        for call in turn.tool_calls:
            if call.declared or call.name in ("function_call_output", "tool_result"):
                continue
            actual_call_count += 1
            tool_types[call.name] = tool_types.get(call.name, 0) + 1
            # Test/edit detection from the tool's input/arguments.
            arg_text = ""
            inp = call.input if call.input is not None else call.arguments
            if isinstance(inp, dict):
                cmd = inp.get("command") or inp.get("cmd")
                arg_text = cmd if isinstance(cmd, str) else json.dumps(inp)
            elif isinstance(inp, str):
                arg_text = inp
            if command_runs_tests(arg_text):
                has_test = True
                test_commands.append(arg_text)
            if is_code_edit(call.name, inp):
                has_edit = True

    stats = TrajectoryStats(
        turns=len(turns),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        has_tool_calls=actual_call_count > 0,
        tool_call_count=actual_call_count,
        has_failure_correction=any(t.is_failure_correction for t in turns),
        has_test_execution=has_test,
        has_code_edit=has_edit,
        tool_types=tool_types,
        test_commands=test_commands,
    )
    return Trajectory(
        session_id=session_id,
        task=task,
        languages=languages_seen,
        providers=providers_seen,
        turns=turns,
        stats=stats,
    )


def build_trajectories(rows: list[dict[str, Any]]) -> list[Trajectory]:
    """Group trace *rows* by session id into one trajectory per session."""
    session_ids: list[str] = []
    for row in rows:
        sid = row.get("sessionId") or row.get("session_id")
        if sid and sid not in session_ids:
            session_ids.append(sid)
    return [build_trajectory_from_rows(sid, rows) for sid in session_ids]
