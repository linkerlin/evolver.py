"""Collect phase: read memory, user docs, session logs, system health.

Equivalent to evolver/src/evolve/pipeline/collect.js.
"""

from __future__ import annotations

import os
import platform
import time
from pathlib import Path
from typing import Any

from evolver.evolve.pipeline.session_format import (
    format_cursor_transcript,
    format_session_log,
)

# Re-export for public collect API (sessionFormat contracts).
__all__ = [
    "check_system_health",
    "collect_phase",
    "diagnose_session_log",
    "diagnose_session_source_empty",
    "format_cursor_transcript",
    "format_session_log",
    "get_mutation_directive",
    "read_memory_snippet",
    "read_real_session_log",
    "read_user_snippet",
    "reset_session_source_warning",
]
from evolver.gep.analyzer import analyze, diagnosis_to_dict
from evolver.gep.living_memory import format_risk_warnings, load_living_memory
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


def diagnose_session_log(log: str) -> dict[str, Any] | None:
    if not log or log.startswith("["):
        return None
    lower = log.lower()
    if not any(token in lower for token in ("traceback", "error", "exception")):
        return None
    return diagnosis_to_dict(analyze(log))


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


def _list_openclaw_agents(homedir: Path) -> list[str]:
    agents_root = homedir / ".openclaw" / "agents"
    if not agents_root.is_dir():
        return []
    names: list[str] = []
    try:
        for child in agents_root.iterdir():
            if child.is_dir() and (child / "sessions").is_dir():
                names.append(child.name)
    except OSError:
        return []
    return sorted(names)


def diagnose_session_source_empty(
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Diagnose missing agent session sources (Sprint 15.6).

    Accepts optional overrides (Node camelCase + snake_case):
    ``homedir``, ``agentName``/``agent_name``, ``sessionSource``/
    ``session_source``, ``cursorTranscriptsDir``/``cursor_transcripts_dir``,
    ``agentSessionsDir``/``agent_sessions_dir``.
    """
    opts = dict(diagnostics or {})
    home_raw = (
        opts.get("homedir")
        or opts.get("home")
        or os.environ.get("HOME")
        or os.environ.get("USERPROFILE")
    )
    homedir = Path(str(home_raw)) if home_raw else Path.home()

    agent_name = (
        str(
            opts.get("agentName")
            or opts.get("agent_name")
            or os.environ.get("AGENT_NAME")
            or "main"
        ).strip()
        or "main"
    )
    session_source = (
        str(
            opts.get("sessionSource")
            or opts.get("session_source")
            or os.environ.get("EVOLVER_SESSION_SOURCE")
            or "auto"
        )
        .strip()
        .lower()
        or "auto"
    )
    cursor_dir = str(
        opts.get("cursorTranscriptsDir")
        or opts.get("cursor_transcripts_dir")
        or os.environ.get("EVOLVER_CURSOR_TRANSCRIPTS_DIR")
        or os.environ.get("CURSOR_TRACE_DIR")
        or ""
    ).strip()
    agent_sessions = opts.get("agentSessionsDir") or opts.get("agent_sessions_dir")
    if agent_sessions:
        agent_sessions_dir = Path(str(agent_sessions))
    else:
        env_sessions = os.environ.get("AGENT_SESSIONS_DIR", "").strip()
        agent_sessions_dir = (
            Path(env_sessions)
            if env_sessions
            else homedir / ".openclaw" / "agents" / agent_name / "sessions"
        )

    available = _list_openclaw_agents(homedir)
    agent_exists = agent_sessions_dir.is_dir()
    hints: list[str] = []

    # IDE transcript presence for cursor mode.
    ide_dirs = [
        homedir / ".cursor",
        homedir / ".claude",
        homedir / ".codex",
    ]
    if cursor_dir:
        ide_dirs.insert(0, Path(cursor_dir))
    ide_present = any(p.is_dir() for p in ide_dirs)

    if session_source in ("openclaw", "auto") and not agent_exists:
        if session_source == "openclaw":
            hints.append(
                f"EVOLVER_SESSION_SOURCE=openclaw but AGENT_SESSIONS_DIR "
                f"({agent_sessions_dir}) does not exist."
            )
        if available:
            hints.append(
                f'AGENT_NAME="{agent_name}" sessions dir missing. '
                f"Available OpenClaw agents: {', '.join(available)}."
            )
        elif session_source == "auto" and not ide_present:
            hints.append(
                "No session sources detected under ~/.openclaw/agents or "
                "IDE transcript dirs (~/.cursor, ~/.claude, ~/.codex)."
            )

    if session_source == "cursor" and not ide_present:
        hints.append(
            "EVOLVER_SESSION_SOURCE=cursor but none of ~/.cursor, ~/.claude, ~/.codex "
            "(or EVOLVER_CURSOR_TRANSCRIPTS_DIR) exist."
        )

    # When every source is absent under auto, ensure the global hint is present.
    if (
        session_source == "auto"
        and not agent_exists
        and not available
        and not ide_present
        and not any("No session sources detected" in h for h in hints)
    ):
        hints.append("No session sources detected.")

    return {
        "memory_present": (get_workspace_root() / "MEMORY.md").exists(),
        "user_present": (get_workspace_root() / "USER.md").exists(),
        "logs_present": bool(_find_session_logs()),
        "agentSessionsDir": str(agent_sessions_dir),
        "agentSessionsDirExists": agent_exists,
        "availableOpenClawAgents": available,
        "sessionSource": session_source,
        "agentName": agent_name,
        "hints": hints,
    }


def reset_session_source_warning() -> dict[str, Any]:
    """Reset and return the current session source diagnostic state.

    Clears any transient warning flags so the next cycle starts fresh.
    Equivalent to evolver/src/evolve/pipeline/collect.js::resetSessionSourceWarning.
    """
    return diagnose_session_source_empty()


async def collect_phase(ctx: dict[str, Any]) -> dict[str, Any]:
    ctx["memory_snippet"] = read_memory_snippet()
    ctx["user_snippet"] = read_user_snippet()
    raw_log = read_real_session_log()
    # Prefer multi-format JSONL normalisation when the log looks like JSONL.
    if raw_log and not raw_log.startswith("[") and "{" in raw_log[:200]:
        formatted = format_session_log(raw_log)
        ctx["session_log"] = formatted or raw_log
    else:
        ctx["session_log"] = raw_log
    ctx["mutation_directive"] = get_mutation_directive(ctx["session_log"])
    ctx["failure_diagnosis"] = diagnose_session_log(ctx["session_log"])
    ctx["health_report"] = check_system_health()
    living_memory = load_living_memory()
    ctx["living_memory"] = living_memory
    warnings = format_risk_warnings(living_memory)
    if warnings:
        ctx["living_memory_warnings"] = warnings
    ctx["scan_time_ms"] = int(time.time() * 1000)
    ctx["file_list"] = []
    ctx["session_source_diagnostic"] = diagnose_session_source_empty()
    return ctx
