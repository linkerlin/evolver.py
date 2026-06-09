"""Build desensitized execution traces for capsules.

Equivalent to evolver/src/gep/executionTrace.js.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

TraceLevel = Literal["none", "minimal", "full"]


def get_trace_level() -> TraceLevel:
    raw = os.environ.get("EVOLVER_TRACE_LEVEL", "minimal").lower().strip()
    if raw in ("none", "minimal", "full"):
        return raw  # type: ignore[return-value]
    return "minimal"


def desensitize_file_path(path: str) -> str:
    """Remove user-specific path prefixes."""
    home = str(Path.home())
    p = path.replace(home, "~")
    # Collapse workspace-specific segments to <workspace>
    p = re.sub(r"[~\w/\\]+/([^/\\]+/){1,3}(src|lib|test|evolver|\.evolver)", "<workspace>/.../\\2", p)
    return p


def extract_error_signature(text: str) -> str | None:
    if not text:
        return None
    # First non-empty line containing "Error" or "Exception"
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "Error" in line or "Exception" in line:
            return line[:200]
    return None


def infer_tool_chain(cmd: str) -> str:
    cmd = cmd.strip().lower()
    if cmd.startswith("python") or cmd.endswith(".py"):
        return "python"
    if cmd.startswith("node") or cmd.endswith(".js"):
        return "node"
    if cmd.startswith("pytest"):
        return "pytest"
    if cmd.startswith("ruff"):
        return "ruff"
    if cmd.startswith("mypy"):
        return "mypy"
    if cmd.startswith("git"):
        return "git"
    return "shell"


def classify_blast_level(files: int, lines: int) -> Literal["tiny", "small", "medium", "large"]:
    if files <= 1 and lines <= 20:
        return "tiny"
    if files <= 3 and lines <= 100:
        return "small"
    if files <= 10 and lines <= 500:
        return "medium"
    return "large"


def build_execution_trace(
    commands: list[str],
    outputs: list[str],
    file_changes: list[str] | None = None,
) -> list[dict]:
    level = get_trace_level()
    if level == "none":
        return []

    trace: list[dict] = []
    for cmd, out in zip(commands, outputs):
        entry: dict = {
            "tool": infer_tool_chain(cmd),
            "command_preview": cmd[:120],
        }
        if level == "full":
            entry["output_preview"] = out[:500]
            err = extract_error_signature(out)
            if err:
                entry["error_signature"] = err
        if file_changes:
            entry["files_touched"] = len(file_changes)
        trace.append(entry)
    return trace
