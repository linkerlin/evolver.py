"""Benchmark task format (S26.1) — wikiskill-compatible task packs.

No Node.js equivalent; evolver.py addition.

A task pack is a JSON list of tasks::

    {"id": "spec-format1-1", "split": "train",
     "title": "Format products according to spec",
     "prompt": "Read spec.md and products.json...",
     "sandbox": {"spec.md": "...", "products.json": "..."},
     "grader": {"type": "exact", "file": "output.txt",
                "expected": "alpha|35|active\\n..."}}

Graders: ``exact`` / ``contains`` / ``json_field`` / ``code_stdout``.
Missing deliverables score 0 — graders never crash (wikiskill honesty).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

GRADER_TYPES: frozenset[str] = frozenset({"exact", "contains", "json_field", "code_stdout"})
SPLITS: frozenset[str] = frozenset({"train", "val"})
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def validate_tasks(tasks: list[Any]) -> list[str]:
    """Return a list of human-readable errors; empty list means valid."""
    errors: list[str] = []
    seen: set[str] = set()
    if not isinstance(tasks, list):
        return ["tasks must be a JSON list"]
    for i, t in enumerate(tasks):
        where = f"task[{i}]"
        if not isinstance(t, dict):
            errors.append(f"{where}: not an object")
            continue
        tid = t.get("id")
        if not isinstance(tid, str) or not _SLUG_RE.match(tid):
            errors.append(f"{where}: id must be a lowercase slug, got {tid!r}")
        elif tid in seen:
            errors.append(f"{where}: duplicate id {tid!r}")
        else:
            seen.add(tid)
        if t.get("split") not in SPLITS:
            errors.append(f"{where}: split must be 'train' or 'val', got {t.get('split')!r}")
        if not isinstance(t.get("prompt"), str) or not t["prompt"]:
            errors.append(f"{where}: prompt must be a non-empty string")
        sandbox = t.get("sandbox")
        if not isinstance(sandbox, dict) or not sandbox:
            errors.append(f"{where}: sandbox must be a non-empty object")
        else:
            for name in sandbox:
                if not isinstance(name, str) or not name or ".." in name or name.startswith("/"):
                    errors.append(f"{where}: sandbox file name rejected: {name!r}")
        errors.extend(_validate_grader(t.get("grader"), where))
    return errors


def _validate_grader(grader: Any, where: str) -> list[str]:
    if not isinstance(grader, dict):
        return [f"{where}: grader must be an object"]
    gtype = grader.get("type")
    if gtype not in GRADER_TYPES:
        return [f"{where}: grader.type must be one of {sorted(GRADER_TYPES)}, got {gtype!r}"]
    if not isinstance(grader.get("file"), str) or not grader["file"]:
        return [f"{where}: grader.file must be a non-empty string"]
    if gtype in ("exact", "contains") and not isinstance(grader.get("expected"), str):
        return [f"{where}: grader.{gtype} requires string 'expected'"]
    if gtype == "json_field" and not isinstance(grader.get("path"), str):
        return [f"{where}: grader.json_field requires string 'path'"]
    if gtype == "json_field" and "expected" not in grader:
        return [f"{where}: grader.json_field requires 'expected'"]
    if gtype == "code_stdout" and not (isinstance(grader.get("script"), str) and grader["script"]):
        return [f"{where}: grader.code_stdout requires string 'script' (path in sandbox)"]
    return []


def materialize(task: dict[str, Any], root: Path, *, force: bool = True) -> Path:
    """Write the task's sandbox files into ``root/<task-id>/``.

    ``force=True`` deletes every file under the sandbox dir that the task
    spec does not declare — the phantom-scoring defense (stale artifacts
    from a previous rollout must never be graded). Idempotent.
    """
    sandbox = root / str(task["id"])
    sandbox.mkdir(parents=True, exist_ok=True)
    declared = set(task.get("sandbox") or {})
    if force:
        for existing in sandbox.rglob("*"):
            rel = existing.relative_to(sandbox).as_posix()
            if existing.is_file() and rel not in declared:
                existing.unlink()
            elif existing.is_dir():
                shutil.rmtree(existing, ignore_errors=True)
    for name, content in (task.get("sandbox") or {}).items():
        target = sandbox / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
    return sandbox


__all__ = [
    "GRADER_TYPES",
    "SPLITS",
    "materialize",
    "validate_tasks",
]
