"""Task-recall hook — recall relevant capsules on user request.

Equivalent to ``evolver/src/adapters/scripts/evolver-task-recall.js``.

Triggered when the user types ``@evolver recall`` or similar. Queries the
memory graph for similar scenarios and returns the most-relevant capsule
summaries as additional context.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_RECALL_TRIGGERS = ("@evolver recall", "@evolver-recall", "@evolver:recall")


def _query_memory_graph(
    graph_path: Path,
    query: str,
    limit: int = 3,
) -> list[dict[str, object]]:
    """Return up to *limit* entries whose signals/note mention *query* tokens.

    Simple token-overlap matching (no embedding model required). Each query
    token is lowercased; an entry matches if any token appears in its signals
    list or outcome note.
    """
    if not graph_path.exists():
        return []
    tokens = {t.lower() for t in query.split() if len(t) > 2}
    if not tokens:
        return []
    try:
        text = graph_path.read_text(encoding="utf-8").strip()
        if not text:
            return []
    except OSError:
        return []

    scored: list[tuple[int, dict[str, object]]] = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        # Build a searchable haystack from signals + note.
        signals = entry.get("signals")
        haystack_parts: list[str] = []
        if isinstance(signals, list):
            haystack_parts.extend(str(s) for s in signals)
        outcome = entry.get("outcome")
        if isinstance(outcome, dict):
            note = outcome.get("note", "")
            if isinstance(note, str):
                haystack_parts.append(note)
        haystack = " ".join(haystack_parts).lower()
        score = sum(1 for t in tokens if t in haystack)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in scored[:limit]]


def build_recall_output(prompt: str) -> dict[str, str]:
    """Build the task-recall JSON output from a user prompt."""
    # Only act on explicit recall triggers.
    lower = prompt.lower()
    if not any(trigger in lower for trigger in _RECALL_TRIGGERS):
        return {}

    query = prompt
    for trigger in _RECALL_TRIGGERS:
        query = query.replace(trigger, "").strip()

    try:
        from evolver.adapters.scripts.runtime_paths import (  # noqa: PLC0415
            find_evolver_root,
            find_memory_graph,
        )

        evolver_root = find_evolver_root()
        graph_path = find_memory_graph(evolver_root)
    except ImportError:
        return {}

    results = _query_memory_graph(graph_path, query or prompt)
    if not results:
        return {}

    lines = [f"[Evolver Recall] {len(results)} relevant past outcome(s):"]
    for entry in results:
        outcome = entry.get("outcome")
        if not isinstance(outcome, dict):
            outcome = {}
        status = outcome.get("status", "?")
        note = outcome.get("note", "")
        signals = entry.get("signals")
        sig_str = ", ".join(signals[:3]) if isinstance(signals, list) else ""
        lines.append(f"  [{status}] signals=[{sig_str}] {note}"[:200])

    ctx = "\n".join(lines)
    return {"additional_context": ctx, "additionalContext": ctx}


def main() -> None:
    try:
        prompt = sys.stdin.read().strip()
    except OSError:
        prompt = ""
    try:
        output = build_recall_output(prompt)
    except Exception:
        output = {}
    sys.stdout.write(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
