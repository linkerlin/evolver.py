"""Session scratch pad (VISTA WORKING.md analogue).

Durable laws stay in the gene library and ``LESSONS_LEARNED.md``. This file
is the current session's tactical scratch: a hard 16_000-character quota,
val-sealed on read and write, archived and unlinked when a session starts,
accepts, or stops incomplete. The bytes live under ``<EVOLUTION_DIR>/`` and
are not product source.

Host text written here is a clue (``source=host_working``), never a gate input.
No Node.js equivalent.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from evolver.gep.paths import get_evolution_dir

WORKING_FILENAME: Final = "WORKING_SESSION.md"
ARCHIVE_DIRNAME: Final = "working_archive"
MAX_WORKING_CHARS: Final = 16_000
WORKING_CLUE_MAX_CHARS: Final = 3_000
WORKSPACE_FACT_PREFIX: Final = "in this workspace:"
_WORKSPACE_FACT_RE: Final = re.compile(
    r"^\s*(?:[-*]\s*)?in this workspace\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)


def working_path() -> Path:
    return get_evolution_dir() / WORKING_FILENAME


def archive_dir() -> Path:
    return get_evolution_dir() / ARCHIVE_DIRNAME


def read_working() -> str:
    """Current scratch, redacted. Missing file reads as empty."""
    path = working_path()
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    from evolver.gep.val_seal import redact

    scrubbed, _report = redact(text, where="working_memory")
    return scrubbed


def render_working_clue(max_chars: int = WORKING_CLUE_MAX_CHARS) -> str:
    """One ``[host_working]`` clue line for the dispatch prompt, or ``""``.

    Bounded below the prompt budget; the omitted tail stays readable through
    ``swarm_boot``.
    """
    text = read_working().strip()
    if not text:
        return ""
    if len(text) > max_chars:
        omitted = len(text) - max_chars
        text = (
            f"{text[:max_chars]}\n... (+{omitted} chars omitted; swarm_boot returns the full text)"
        )
    return f"- [host_working] {text}"


def write_working(content: str) -> dict[str, Any]:
    """Replace the scratch pad. Empty text and over-quota text are refused."""
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty_working")
    from evolver.gep.val_seal import redact

    scrubbed, report = redact(content, where="working_memory")
    if len(scrubbed) > MAX_WORKING_CHARS:
        raise ValueError(f"working_over_quota: {len(scrubbed)} chars exceeds {MAX_WORKING_CHARS}")
    if not scrubbed.endswith("\n"):
        scrubbed += "\n"
    path = working_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text(scrubbed, encoding="utf-8")
    temporary.replace(path)
    return {
        "path": str(path),
        "chars": len(scrubbed),
        "redacted": int(report.get("redacted") or 0),
        "source": "host_working",
    }


def archive_and_clear(reason: str) -> dict[str, Any]:
    """Archive non-empty scratch, then unlink it. Missing file is a no-op.

    The archive is written before the unlink. A failed archive leaves the
    scratch in place — the only copy is not deleted.
    """
    path = working_path()
    if not path.is_file():
        return {"archived": None, "cleared": False}
    content = path.read_text(encoding="utf-8")
    archived: str | None = None
    if content.strip():
        from evolver.gep.val_seal import redact

        scrubbed, _report = redact(content, where="working_memory")
        if not scrubbed.endswith("\n"):
            scrubbed += "\n"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", reason).strip("_") or "boundary"
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        dest = archive_dir() / f"{safe}_{stamp}.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(scrubbed, encoding="utf-8")
        archived = str(dest)
    path.unlink()
    return {"archived": archived, "cleared": True}


def format_workspace_facts_section(
    facts: list[str],
    *,
    ruled_out: list[str] | None = None,
) -> str:
    """Format tactical workspace-local facts for ``WORKING_SESSION.md`` (Harness2 §3.2).

    Workspace facts (file paths, line numbers, active task IDs, ruled-out dead
    ends) belong in the session scratch pad with an explicit ``in this workspace:``
    marker so they are automatically archived and unlinked at session end, never
    leaking into durable ``genes.json`` or library snapshots.
    """
    lines: list[str] = ["## Workspace Facts (session-local)"]
    for raw in facts:
        item = str(raw or "").strip()
        if not item:
            continue
        if not item.lower().startswith("in this workspace:"):
            item = f"{WORKSPACE_FACT_PREFIX} {item}"
        lines.append(f"- {item}")
    if ruled_out:
        lines.append("")
        lines.append("## Ruled Out (session-local)")
        for raw in ruled_out:
            item = str(raw or "").strip()
            if item:
                lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def extract_workspace_facts(text: str | None = None) -> list[str]:
    """Return all ``in this workspace: ...`` facts from *text* (or live scratch)."""
    source = read_working() if text is None else str(text)
    found: list[str] = []
    for line in source.splitlines():
        match = _WORKSPACE_FACT_RE.match(line)
        if match:
            fact = match.group(1).strip()
            if fact and fact not in found:
                found.append(fact)
    return found


__all__ = [
    "ARCHIVE_DIRNAME",
    "MAX_WORKING_CHARS",
    "WORKING_CLUE_MAX_CHARS",
    "WORKING_FILENAME",
    "WORKSPACE_FACT_PREFIX",
    "archive_and_clear",
    "archive_dir",
    "extract_workspace_facts",
    "format_workspace_facts_section",
    "read_working",
    "render_working_clue",
    "working_path",
    "write_working",
]
