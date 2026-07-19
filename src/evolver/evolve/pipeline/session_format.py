"""Multi-agent session log formatters (Sprint 15.6).

Ports ``formatSessionLog`` / ``formatCursorTranscript`` contracts from
``evolver/test/sessionFormat.test.js`` covering OpenClaw, Claude Code,
Cursor JSONL, Codex CLI, and Manus event shapes.
"""

from __future__ import annotations

import json
import re
from typing import Any

_META_MARKERS = frozenset({"HEARTBEAT_OK", "NO_REPLY", "NO_RESPONSE_NEEDED", "[META]"})
_XML_TAG_RE = re.compile(r"</?[a-zA-Z_][\w:-]*(?:\s[^>]*)?>")
_TOOL_CALL_PLAIN_RE = re.compile(r"^\[Tool call\]\s+(\S+)", re.I)
_TOOL_RESULT_PLAIN_RE = re.compile(r"^\[Tool result\]", re.I)
_PARAM_LINE_RE = re.compile(r"^\s{2,}\S")


def _is_meta_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped in _META_MARKERS:
        return True
    upper = stripped.upper()
    return upper in _META_MARKERS


def _content_parts(content: Any) -> tuple[str, list[str]]:
    """Return (visible_text, tool_names) from a message content field."""
    texts: list[str] = []
    tools: list[str] = []

    if content is None:
        return "", tools
    if isinstance(content, str):
        return content, tools
    if not isinstance(content, list):
        return str(content), tools

    for block in content:
        if not isinstance(block, dict):
            if isinstance(block, str) and block.strip():
                texts.append(block)
            continue
        btype = str(block.get("type") or "")
        if btype in ("thinking", "redacted_thinking"):
            continue
        if btype in ("text", "input_text", "output_text"):
            t = block.get("text")
            if isinstance(t, str) and t:
                texts.append(t)
            continue
        if btype in ("toolCall", "tool_use", "function_call"):
            name = str(block.get("name") or block.get("tool") or "tool")
            tools.append(name)
            continue
        # Unknown block with text
        t = block.get("text")
        if isinstance(t, str) and t and btype not in ("input",):
            texts.append(t)
    return " ".join(texts).strip(), tools


def _format_role_line(role: str, text: str, tools: list[str]) -> str | None:
    role_u = role.upper()
    if role_u in ("USER", "HUMAN"):
        label = "USER"
    elif role_u in ("ASSISTANT", "AI", "MODEL"):
        label = "ASSISTANT"
    elif role_u in ("TOOL", "TOOLRESULT", "TOOL_RESULT"):
        return None  # handled separately
    else:
        label = role_u or "MESSAGE"

    if _is_meta_text(text) and not tools:
        return None
    if not text and not tools:
        return None

    tool_suffix = "".join(f" [TOOL: {name}]" for name in tools)
    body = text if text else ""
    line = f"**{label}**: {body}{tool_suffix}".rstrip()
    if line.endswith(":"):
        # empty body with tools only
        if tools and not body:
            return f"**{label}**:{tool_suffix}"
        return None
    return line


def _parse_one_record(obj: dict[str, Any]) -> list[str]:  # noqa: PLR0911, PLR0912, PLR0915
    """Convert one JSONL object into zero or more formatted lines."""
    lines: list[str] = []
    rtype = str(obj.get("type") or "")

    # Skip pure status / session lifecycle noise.
    if rtype in (
        "session.created",
        "status_update",
        "session_meta",
        "heartbeat",
    ):
        return lines

    if obj.get("isMeta") is True:
        return lines

    # ---- Manus ----
    if rtype == "user_message":
        um = obj.get("user_message") if isinstance(obj.get("user_message"), dict) else {}
        text = str(um.get("content") or "")
        line = _format_role_line("user", text, [])
        if line:
            lines.append(line)
        return lines
    if rtype == "assistant_message":
        am = obj.get("assistant_message") if isinstance(obj.get("assistant_message"), dict) else {}
        text = str(am.get("content") or "")
        line = _format_role_line("assistant", text, [])
        if line:
            lines.append(line)
        return lines
    if rtype == "tool_used":
        tu = obj.get("tool_used") if isinstance(obj.get("tool_used"), dict) else {}
        name = str(tu.get("name") or "tool")
        lines.append(f"[TOOL: {name}]")
        return lines

    # ---- Codex item.* ----
    if rtype in ("item.added", "item.completed") and isinstance(obj.get("item"), dict):
        item = obj["item"]
        itype = str(item.get("type") or "")
        if itype == "function_call":
            name = str(item.get("name") or "tool")
            lines.append(f"[TOOL: {name}]")
            return lines
        if itype == "function_call_output":
            output = item.get("output")
            text = (
                output
                if isinstance(output, str)
                else (json.dumps(output, ensure_ascii=False) if output is not None else "")
            )
            # Skip short success-only outputs.
            if text.strip().lower() in ("success", "ok", "done", ""):
                return lines
            if len(text.strip()) < 8 and text.strip().lower() in ("true", "false", "null"):
                return lines
            if text.strip():
                lines.append(f"[TOOL RESULT] {text.strip()[:500]}")
            return lines
        if itype == "message":
            role = str(item.get("role") or "assistant")
            text, tools = _content_parts(item.get("content"))
            line = _format_role_line(role, text, tools)
            if line:
                lines.append(line)
            return lines
        return lines

    # ---- Claude / OpenClaw tool_result top-level ----
    if rtype == "tool_result":
        content = obj.get("content")
        text = (
            content
            if isinstance(content, str)
            else (json.dumps(content, ensure_ascii=False) if content is not None else "")
        )
        if text.strip():
            lines.append(f"[TOOL RESULT] {text.strip()[:500]}")
        return lines

    # ---- OpenClaw type=message / Claude type=user|assistant / Cursor role ----
    message = obj.get("message") if isinstance(obj.get("message"), dict) else None
    role = ""
    content: Any = None

    if message is not None:
        role = str(message.get("role") or obj.get("role") or rtype or "")
        content = message.get("content")
        # OpenClaw toolResult role
        if role == "toolResult" or str(message.get("role")) == "toolResult":
            tr = obj.get("content")
            if tr is None:
                tr = content
            text = (
                tr
                if isinstance(tr, str)
                else (json.dumps(tr, ensure_ascii=False) if tr is not None else "")
            )
            if text.strip():
                lines.append(f"[TOOL RESULT] {text.strip()[:500]}")
            return lines
        err = message.get("errorMessage") or obj.get("errorMessage")
        if isinstance(err, str) and err.strip():
            lines.append(f"[LLM ERROR] {err.strip()}")
    elif obj.get("role"):
        role = str(obj.get("role") or "")
        content = obj.get("content") or (
            obj.get("message", {}).get("content") if isinstance(obj.get("message"), dict) else None
        )
        # Cursor often nests message.content
        if content is None and isinstance(obj.get("message"), dict):
            content = obj["message"].get("content")
    elif rtype in ("user", "assistant"):
        role = rtype
        content = obj.get("content")
        if content is None and isinstance(obj.get("message"), dict):
            content = obj["message"].get("content")
            role = str(obj["message"].get("role") or role)

    if role or content is not None:
        # If type is user/assistant without message, content may be on message
        if content is None and isinstance(obj.get("message"), dict):
            content = obj["message"].get("content")
            role = str(obj["message"].get("role") or role or rtype)
        if not role:
            role = rtype or "assistant"
        text, tools = _content_parts(content)
        # OpenClaw may put string content directly on message
        if not text and isinstance(message, dict) and isinstance(message.get("content"), str):
            text = message["content"]
        line = _format_role_line(role, text, tools)
        if line:
            lines.append(line)
        # Also surface errorMessage when present alongside content
        if message is not None:
            err = message.get("errorMessage")
            if isinstance(err, str) and err.strip() and not any("[LLM ERROR]" in x for x in lines):
                lines.append(f"[LLM ERROR] {err.strip()}")
        return lines

    return lines


def format_session_log(raw: str, *, max_lines: int = 2_000) -> str:
    """Format multi-agent session JSONL into a readable transcript.

    Supports OpenClaw, Claude Code, Cursor JSONL, Codex CLI, and Manus
    event shapes. Skips malformed lines and collapses exact duplicates.
    """
    if not raw or raw.startswith("["):
        return raw if raw else ""

    out_lines: list[str] = []
    prev: str | None = None
    repeat = 0

    def _flush_repeat() -> None:
        nonlocal repeat
        if repeat > 0 and out_lines:
            out_lines.append(f"  (Repeated {repeat} times)")
        repeat = 0

    for raw_line in raw.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped[0] not in "{[":
            continue
        try:
            obj = json.loads(stripped)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        for line in _parse_one_record(obj):
            if prev is not None and line == prev:
                repeat += 1
                continue
            _flush_repeat()
            out_lines.append(line)
            prev = line
            if len(out_lines) >= max_lines:
                _flush_repeat()
                return "\n".join(out_lines)
    _flush_repeat()
    return "\n".join(out_lines)


def format_cursor_transcript(raw: str) -> str:  # noqa: PLR0912
    """Sanitize a Cursor-style plain-text transcript.

    Keeps user/assistant turns and ``[Tool call] Name`` markers; drops
    tool parameters, tool results, SSE data lines, and XML tags.
    """
    if not raw:
        return ""
    out: list[str] = []
    skip_params = False
    for line in raw.splitlines():
        stripped = line.strip()
        # SSE
        if stripped.startswith("data:") and "event:" not in stripped[:20]:
            continue
        # XML tags
        if _XML_TAG_RE.fullmatch(stripped) or (stripped.startswith("<") and stripped.endswith(">")):
            continue
        cleaned = _XML_TAG_RE.sub("", line)
        if not cleaned.strip() and not line.strip():
            continue

        if _TOOL_CALL_PLAIN_RE.match(stripped):
            out.append(stripped)
            skip_params = True
            continue
        if _TOOL_RESULT_PLAIN_RE.match(stripped):
            skip_params = True
            continue
        if skip_params:
            if _PARAM_LINE_RE.match(line) or (
                stripped
                and not stripped.endswith(":")
                and not stripped.startswith("user:")
                and not stripped.startswith("A:")
                and not stripped.startswith("assistant:")
            ):
                # Drop param lines and tool result body until next speaker/marker.
                if (stripped.endswith(":") and stripped in ("user:", "A:", "assistant:")) or (
                    stripped.startswith("user:")
                    or stripped.startswith("A:")
                    or stripped.startswith("assistant:")
                ) or (
                    stripped.startswith("[Tool")
                    or stripped.startswith("user")
                    or stripped.startswith("A")
                ):
                    skip_params = False
                else:
                    continue
            else:
                skip_params = False

        if skip_params and _PARAM_LINE_RE.match(line):
            continue

        # After tool call, skip indented params
        if out and out[-1].startswith("[Tool call]") and _PARAM_LINE_RE.match(line):
            continue

        out.append(cleaned.rstrip() if cleaned != line else line)
    return "\n".join(out)


__all__ = ["format_cursor_transcript", "format_session_log"]
