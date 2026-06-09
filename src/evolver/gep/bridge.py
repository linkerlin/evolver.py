"""Write prompt artifacts and parse sessions_spawn(...) bridge payloads.

Equivalent to evolver/src/gep/bridge.js.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from evolver.config import PROMPT_MAX_CHARS


def clip(text: str, max_chars: int = PROMPT_MAX_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + "\n...[truncated]...\n" + text[-half:]


def write_prompt_artifact(prompt: str, path: Path | str | None = None) -> Path:
    if path is None:
        from evolver.gep.paths import get_evolution_dir

        path = get_evolution_dir() / "last_prompt.md"
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(prompt, encoding="utf-8")
    return p


def render_sessions_spawn_call(payload: dict[str, Any]) -> str:
    """Render a sessions_spawn(...) call with compact JSON."""
    return "sessions_spawn(" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ")"


def extract_first_spawn_payload(text: str | None) -> str | None:
    """Extract the raw JSON string from the first sessions_spawn(...) call."""
    if not isinstance(text, str) or not text:
        return None
    marker = "sessions_spawn("
    idx = text.find(marker)
    if idx == -1:
        return None
    start = idx + len(marker)
    # There must be nothing but whitespace between marker and the opening brace
    brace = start
    while brace < len(text) and text[brace].isspace():
        brace += 1
    if brace >= len(text) or text[brace] != "{":
        return None

    depth = 0
    in_string = False
    escape = False
    i = brace
    while i < len(text):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[brace : i + 1]
        i += 1
    return None


def parse_first_spawn_call(text: str | None) -> dict[str, Any] | None:
    raw = extract_first_spawn_payload(text)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
