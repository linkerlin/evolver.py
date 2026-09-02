"""Deterministic graders (S26.1) — four scorers, all 0.0/1.0, never crash.

No Node.js equivalent; evolver.py addition.

A missing deliverable, a parse failure, or a timeout scores 0.0; grading a
task can never raise. Self-consistency contract: an expected answer written
back into the sandbox MUST score 1.0 (enforced by tests).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

CODE_STDOUT_TIMEOUT_S = 60.0


def _read(sandbox: Path, rel: str) -> str:
    return (sandbox / rel).read_text(encoding="utf-8", errors="replace")


def _normalize(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def grade(task: dict[str, Any], sandbox: Path) -> float:
    """Grade the task's deliverable inside *sandbox*; returns 0.0-1.0."""
    try:
        grader = task.get("grader") or {}
        gtype = grader.get("type")
        if gtype == "exact":
            return float(
                _normalize(_read(sandbox, grader["file"])) == _normalize(grader["expected"])
            )
        if gtype == "contains":
            return float(grader["expected"] in _read(sandbox, grader["file"]))
        if gtype == "json_field":
            data = json.loads(_read(sandbox, grader["file"]))
            node: Any = data
            for part in str(grader["path"]).split("."):
                if not part:
                    continue
                node = node[int(part)] if isinstance(node, list) else node[part]
            return float(node == grader["expected"])
        if gtype == "code_stdout":
            proc = subprocess.run(
                [sys.executable, str((sandbox / grader["script"]).resolve())],
                cwd=str(sandbox),
                capture_output=True,
                text=True,
                timeout=CODE_STDOUT_TIMEOUT_S,
                check=False,
                shell=False,
            )
            return float(_normalize(proc.stdout or "") == _normalize(grader["expected"]))
        return 0.0
    except Exception:
        return 0.0


__all__ = ["grade"]
