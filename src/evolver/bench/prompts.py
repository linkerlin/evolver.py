"""Inference prompts for task packs (S26.1c).

No Node.js equivalent; evolver.py addition.

The engine never runs an agent: it prints the prompt, the human (or a
supervisor loop) feeds it to any agent CLI, and ``evolver bench grade``
scores the deliverable afterwards. Same contract as bridge mode — the
prompt is the interface.

Isolation rules (wikiskill Run-4 lessons): the prompt embeds the absolute
working directory and forbids exploring outside it, because ``--in``-style
CWD pinning is not portable across agent CLIs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def inference_prompt(task: dict[str, Any], sandbox: Path) -> str:
    grader = task.get("grader") or {}
    deliverable = grader.get("file") or grader.get("script") or ""
    workdir = sandbox.resolve()
    lines = [
        f"WORKING DIRECTORY: {workdir}",
        "",
        "You are completing a benchmark task. Work ONLY inside the working",
        "directory above — do not read or write anything outside it.",
        "",
        "## Task",
        str(task.get("title") or ""),
        "",
        str(task.get("prompt") or ""),
        "",
        "## Deliverable",
    ]
    if grader.get("type") == "code_stdout":
        lines += [
            f"Write your solution to `{deliverable}` — the grader runs it with",
            "python and compares stdout to the expected output exactly.",
        ]
    else:
        lines += [
            f"Write the final answer to `{deliverable}`.",
            "Grading is exact/structural: follow the task spec literally — no",
            "extra transformations, no summarizing away format clauses.",
        ]
    lines += [
        "",
        "Before finishing, re-read the deliverable and check it against every",
        "clause of the spec (verify-output-readback).",
    ]
    return "\n".join(lines)


__all__ = ["inference_prompt"]
