"""Pipeline shared utilities — session transcript tools.

Equivalent to ``evolver/src/evolve/utils.js``.
Provides ``extract_transcript_cwd`` for extracting working directory from
session transcript JSONL records (Codex, Cursor, Claude Code, etc.).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Transcript CWD extraction
# ---------------------------------------------------------------------------

_CWD_PATHS: list[str] = [
    "payload.cwd",
    "cwd",
    "working_directory",
    "project_dir",
]


def _try_extract_cwd(record: dict[str, Any]) -> str | None:
    """Try to extract cwd from a single transcript record."""
    for path in _CWD_PATHS:
        parts = path.split(".")
        value: Any = record
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extract_transcript_cwd(
    records: list[dict[str, Any]] | None = None,
    *,
    transcript_path: Path | str | None = None,
) -> Path | None:
    """Extract working directory from session transcript records.

    Accepts either a list of pre-parsed records or a path to a JSONL file.
    Returns ``None`` if no cwd is found.

    Handles transcript formats from Codex, Cursor, Claude Code, and others.
    """
    if records is None and transcript_path is not None:
        records = _read_transcript_records(Path(transcript_path))
    if not records:
        return None

    for record in records:
        # session_meta records from Codex carry payload.cwd
        if record.get("type") == "session_meta":
            cwd = _try_extract_cwd(record)
            if cwd:
                return Path(cwd)
        # Direct cwd field (memory graph, session_end)
        cwd = _try_extract_cwd(record)
        if cwd:
            return Path(cwd)

    return None


def _read_transcript_records(transcript_path: Path) -> list[dict[str, Any]]:
    """Read JSONL transcript records from a file."""
    if not transcript_path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with transcript_path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    records.append(obj)
    except OSError:
        return []
    return records


# ---------------------------------------------------------------------------
# Session scope helpers
# ---------------------------------------------------------------------------


def resolve_session_scope(
    cwd: Path | str | None = None,
    *,
    agent_name: str | None = None,
) -> str:
    """Resolve a session scope string from cwd and agent name.

    Used by session_start hooks to derive the EVOLVER_SESSION_SCOPE
    environment variable.
    """
    import hashlib

    parts: list[str] = []
    if cwd:
        parts.append(str(cwd))
    if agent_name:
        parts.append(agent_name)
    if not parts:
        return "default"

    raw = ":".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
