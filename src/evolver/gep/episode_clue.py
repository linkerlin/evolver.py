"""Clue layer (经验即证据 §5.2) — host-reported material, kept apart from the record.

The episode record holds engine-side facts only. What the host says about its
own round — its account, the tool actions the engine never observed — is a
**clue**: it rides in the prompt as a separately-tagged block and never enters
the record, never supports a gate, never enters the acceptance dimension.
Append-only JSONL under ``<EVOLUTION_DIR>/episodes/clues.jsonl``.

Node.js 无等价物 (本阶段新机制)。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Final

from evolver.gep.paths import get_evolution_dir

CLUES_FILENAME: Final = "clues.jsonl"
MAX_CLUE_CHARS: Final = 2000
MAX_CLUES: Final = 5
CLUE_BLOCK_MAX_CHARS: Final = 1200


def clues_path() -> Path:
    return get_evolution_dir() / "episodes" / CLUES_FILENAME


def append_clue(text: str, *, source: str = "host_distill") -> dict[str, Any]:
    """Append one host-reported clue. Tagged with its source — a clue is a
    lead, not evidence, and the tag travels with it into the prompt."""
    clue: dict[str, Any] = {
        "at": time.time(),
        "source": source,
        "text": text[:MAX_CLUE_CHARS],
    }
    path = clues_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(clue, ensure_ascii=False) + "\n")
    return {"ok": True, "source": source, "chars": len(clue["text"])}


def recent_clues(limit: int = MAX_CLUES) -> list[dict[str, Any]]:
    """The most recent clues, oldest first (the prompt reads them in order)."""
    path = clues_path()
    if not path.exists():
        return []
    clues: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if isinstance(row, dict) and isinstance(row.get("text"), str):
                clues.append(row)
    except (OSError, json.JSONDecodeError):
        return []
    return clues[-max(1, limit) :]


def render_clue_block(clues: list[dict[str, Any]], max_chars: int = CLUE_BLOCK_MAX_CHARS) -> str:
    """Render the clue block: each clue tagged with its source, bounded."""
    lines = ["## Host Clues (leads, not evidence — each tagged with its source)"]
    for clue in clues:
        text = str(clue.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"- [{clue.get('source') or 'unknown'}] {text}")
    block = "\n".join(lines)
    return block if len(block) <= max_chars else block[:max_chars] + "\n... (truncated)"


__all__ = [
    "CLUES_FILENAME",
    "CLUE_BLOCK_MAX_CHARS",
    "MAX_CLUES",
    "MAX_CLUE_CHARS",
    "append_clue",
    "clues_path",
    "recent_clues",
    "render_clue_block",
]
