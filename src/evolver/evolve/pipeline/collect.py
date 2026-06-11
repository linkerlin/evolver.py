"""Collect phase: read memory, user docs, session logs, system health.

Equivalent to evolver/src/evolve/pipeline/collect.js.
"""

from __future__ import annotations

import platform
import time
from pathlib import Path
from typing import Any

from evolver.gep.paths import get_repo_root, get_workspace_root


def _read_file_snippet(path: Path, max_chars: int = 4_000) -> str:
    if not path.exists():
        return f"[{path.name.upper()} MISSING]"
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return f"[{path.name.upper()} MISSING]"
    if len(raw) > max_chars:
        return raw[:max_chars] + "\n...[truncated]\n"
    return raw


def read_memory_snippet() -> str:
    return _read_file_snippet(get_workspace_root() / "MEMORY.md")


def read_user_snippet() -> str:
    return _read_file_snippet(get_workspace_root() / "USER.md")


def _find_session_logs() -> list[Path]:
    """Best-effort find platform session logs."""
    logs: list[Path] = []
    repo = get_repo_root()
    if repo:
        # Project-local logs
        for candidate in ("memory/evolution/pipeline_events.jsonl", "memory_graph.jsonl"):
            p = repo / candidate
            if p.exists():
                logs.append(p)
    return logs


def read_real_session_log(max_chars: int = 8_000) -> str:
    logs = _find_session_logs()
    if not logs:
        return "[NO SESSION LOGS FOUND]"
    # Read most recently modified
    logs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return _read_file_snippet(logs[0], max_chars=max_chars)


def get_mutation_directive(log: str) -> str:
    """Infer mutation intent/stability from session log heuristics."""
    text = log.lower()
    error_hits = text.count("error") + text.count("exception") + text.count("traceback")
    if error_hits > 3:
        intent = "repair"
        stability = "unstable"
    elif error_hits > 0:
        intent = "repair"
        stability = "stable"
    elif "todo" in text or "fixme" in text:
        intent = "optimize"
        stability = "stable"
    else:
        intent = "innovate"
        stability = "stable"
    return f"recommended_intent: {intent}\nstability: {stability}\n"


def check_system_health() -> str:
    return (
        f"python_version: {platform.python_version()}\n"
        f"platform: {platform.platform()}\n"
        f"uptime_estimate_s: {int(time.monotonic())}\n"
    )


def diagnose_session_source_empty(diagnostics: dict[str, Any] | None = None) -> dict[str, Any]:
    return diagnostics or {
        "memory_present": (get_workspace_root() / "MEMORY.md").exists(),
        "user_present": (get_workspace_root() / "USER.md").exists(),
        "logs_present": bool(_find_session_logs()),
    }


def reset_session_source_warning() -> dict[str, Any]:
    """Reset and return the current session source diagnostic state.

    Clears any transient warning flags so the next cycle starts fresh.
    Equivalent to evolver/src/evolve/pipeline/collect.js::resetSessionSourceWarning.
    """
    return diagnose_session_source_empty()


def format_cursor_transcript(raw: str) -> str:
    """Sanitize a Cursor-style transcript."""
    lines = raw.splitlines()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("data:") and "event:" not in stripped[:20]:
            # Skip raw SSE data lines
            continue
        out.append(line)
    return "\n".join(out[:1_000])


async def collect_phase(ctx: dict[str, Any]) -> dict[str, Any]:
    ctx["memory_snippet"] = read_memory_snippet()
    ctx["user_snippet"] = read_user_snippet()
    ctx["session_log"] = read_real_session_log()
    ctx["mutation_directive"] = get_mutation_directive(ctx["session_log"])
    ctx["health_report"] = check_system_health()
    ctx["scan_time_ms"] = int(time.time() * 1000)
    ctx["file_list"] = []
    return ctx
