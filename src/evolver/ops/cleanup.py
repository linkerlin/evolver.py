"""Cleanup old logs, events, and state files.

Equivalent to evolver/src/ops/cleanup.js.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from evolver.config import (
    CLEANUP_MAX_AGE_MS,
    CLEANUP_MAX_FILES,
    CLEANUP_MIN_KEEP,
)
from evolver.gep.paths import (
    get_evolution_dir,
    get_logs_dir,
    get_memory_dir,
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _file_age_ms(path: Path) -> int | None:
    try:
        mtime = path.stat().st_mtime
        return _now_ms() - int(mtime * 1000)
    except OSError:
        return None


def cleanup_jsonl(
    path: Path, *, max_age_ms: int = CLEANUP_MAX_AGE_MS, min_keep: int = CLEANUP_MIN_KEEP
) -> dict[str, Any]:
    """Remove stale lines from a JSONL file while keeping at least *min_keep* recent lines."""
    if not path.exists():
        return {"path": str(path), "removed": 0, "kept": 0}
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return {"path": str(path), "removed": 0, "kept": 0, "error": "read_failed"}

    if len(lines) <= min_keep:
        return {"path": str(path), "removed": 0, "kept": len(lines)}

    # Keep the last min_keep lines unconditionally; evaluate older ones by age
    cutoff = _now_ms() - max_age_ms
    kept: list[str] = []
    removed = 0
    # Process from oldest to newest
    for i, line in enumerate(lines):
        if i < len(lines) - min_keep:
            try:
                record = json.loads(line)
                ts = record.get("timestamp") or record.get("ts")
                if isinstance(ts, (int, float)):
                    record_ms = int(ts) if ts > 1e12 else int(ts * 1000)
                elif isinstance(ts, str):
                    # Best-effort ISO parse
                    try:
                        from datetime import datetime

                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        record_ms = int(dt.timestamp() * 1000)
                    except Exception:
                        record_ms = _now_ms()
                else:
                    record_ms = _now_ms()
                if record_ms < cutoff:
                    removed += 1
                    continue
            except json.JSONDecodeError:
                removed += 1
                continue
        kept.append(line)

    if removed > 0:
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(kept)
        tmp.replace(path)

    return {"path": str(path), "removed": removed, "kept": len(kept)}


def cleanup_directory(
    directory: Path,
    *,
    pattern: str = "*",
    max_age_ms: int = CLEANUP_MAX_AGE_MS,
    max_files: int = CLEANUP_MAX_FILES,
    min_keep: int = CLEANUP_MIN_KEEP,
) -> dict[str, Any]:
    """Remove old files from *directory* matching *pattern*."""
    if not directory.exists():
        return {"dir": str(directory), "removed": 0}

    files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for i, f in enumerate(files):
        if i < min_keep:
            continue
        age = _file_age_ms(f)
        if (age is not None and age > max_age_ms) or i >= max_files:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass

    return {"dir": str(directory), "removed": removed}


def run_cleanup() -> dict[str, Any]:
    """Run all cleanup tasks and return summary."""
    results: list[dict[str, Any]] = []

    # Evolution events
    evo_dir = get_evolution_dir()
    results.append(cleanup_jsonl(evo_dir / "events.jsonl"))
    results.append(cleanup_jsonl(evo_dir / "memory_graph.jsonl"))
    results.append(cleanup_jsonl(evo_dir / "reflection_log.jsonl"))

    # Log files
    logs_dir = get_logs_dir()
    results.append(cleanup_directory(logs_dir, pattern="*.log"))

    # Old session archives
    memory_dir = get_memory_dir()
    results.append(cleanup_directory(memory_dir / "evolution", pattern="*.jsonl"))

    total_removed = sum(r.get("removed", 0) for r in results)
    return {"ok": True, "total_removed": total_removed, "details": results}
