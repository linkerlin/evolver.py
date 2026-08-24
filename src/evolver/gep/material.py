"""Material substrate — watermarked incremental ingestion + consumer groups.

Concept harvest from Node v2 ``material/{store,sources,sampling}.js``
(behavioral re-implementation; no code copied). Raw runtime logs (session
logs, llm traces, tool events) enter ONE pipeline here instead of being
re-scanned wholesale every cycle:

- **Watermark dedup** per source file: ``(mtime_ns, size)`` fast-skip;
  grew-with-identical-head ⇒ append-only delta from the old size (aligned
  to the next newline); otherwise full rescan with a bounded full-content
  memo catching rewrite/rename/truncate no-ops.
- **Sampling**: error-bearing lines always kept, consecutive duplicate
  lines collapsed, per-call record cap.
- **Consumer groups**: ``consume(group)`` / ``commit(group, id)`` with
  at-least-once semantics — the cursor only advances on explicit commit.

Sprint 24.8 (演进方案.md §9 概念收割 #6 — thin slice).
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MATERIAL_DIRNAME = "material"
RECORDS_FILENAME = "material.jsonl"
CURSORS_FILENAME = "cursors.json"

#: Head-prefix window for the append-only fast path.
HEAD_BYTES: int = 4096
#: Per-call cap on emitted records (ponytail: flat cap, value-aware sampler
#: if ingestion volume ever demands it).
BATCH_CAP: int = 200
#: Bounded memo of recently-seen full-file hashes per source (rewrite no-op).
FULL_HASH_MEMO: int = 8

ERROR_MARKERS = ("error", "traceback", "exception")


def _material_dir() -> Path:
    from evolver.gep.paths import get_evolution_dir

    return get_evolution_dir() / MATERIAL_DIRNAME


def _records_path() -> Path:
    return _material_dir() / RECORDS_FILENAME


def _cursors_path() -> Path:
    return _material_dir() / CURSORS_FILENAME


def _head_hash(data: bytes) -> str:
    return hashlib.sha256(data[:HEAD_BYTES]).hexdigest()


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Watermarks
# ---------------------------------------------------------------------------


def _load_watermarks() -> dict[str, dict[str, Any]]:
    data = _load_json(_cursors_path(), {})
    wm = data.get("watermarks") if isinstance(data, dict) else None
    return wm if isinstance(wm, dict) else {}


def _save_watermarks(watermarks: dict[str, dict[str, Any]]) -> None:
    data = _load_json(_cursors_path(), {})
    if not isinstance(data, dict):
        data = {}
    data["watermarks"] = watermarks
    _atomic_write_json(_cursors_path(), data)


def _append_records(records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path = _records_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_records(limit: int | None = None) -> list[dict[str, Any]]:
    """All material records in insertion order (tail *limit* when given)."""
    try:
        lines = _records_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines[-limit:] if limit else lines:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                out.append(parsed)
        except json.JSONDecodeError:
            continue
    return out


def _make_record(source_key: str, kind: str, seq: int, text: str) -> dict[str, Any]:
    return {
        "id": f"mat_{int(time.time() * 1000)}_{seq:04d}_{secrets.token_hex(3)}",
        "source": source_key,
        "kind": kind,
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        "text": text[:2000],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _sample_lines(lines: list[str]) -> list[str]:
    """Error lines always kept; consecutive duplicates collapsed."""
    sampled: list[str] = []
    prev_hash: str | None = None
    for raw in lines:
        stripped = raw.rstrip("\n")
        if not stripped.strip():
            continue
        h = hashlib.sha256(stripped.encode("utf-8")).hexdigest()
        if h == prev_hash:
            continue
        prev_hash = h
        lowered = stripped.casefold()
        is_error = any(marker in lowered for marker in ERROR_MARKERS)
        if is_error or len(sampled) < BATCH_CAP:
            sampled.append(stripped)
            if len(sampled) >= BATCH_CAP and not is_error:
                break
    return sampled


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def ingest_file(path: Path | str, *, kind: str = "session_log") -> dict[str, Any]:
    """Incrementally ingest *path*; returns a per-source summary."""
    src = Path(path)
    source_key = str(src)
    summary: dict[str, Any] = {"source": source_key, "added": 0, "mode": "skipped"}
    if not src.exists():
        summary["mode"] = "missing"
        return summary

    stat = src.stat()
    watermarks = _load_watermarks()
    wm = watermarks.get(source_key)

    data = src.read_bytes()

    # Fast-skip: mtime+size unchanged.
    if wm is not None and wm.get("size") == stat.st_size and wm.get("mtime_ns") == stat.st_mtime_ns:
        return summary

    # Rewrite no-op: identical full content seen recently.
    full_hash = hashlib.sha256(data).hexdigest()
    recent = list(wm.get("recent_full_hashes", [])) if wm else []
    if full_hash in recent:
        watermarks[source_key] = {
            **(wm or {}),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "head_hash": _head_hash(data),
            "full_hash": full_hash,
            "recent_full_hashes": recent,
        }
        _save_watermarks(watermarks)
        summary["mode"] = "rewrite_noop"
        return summary

    # Append-only fast path: file grew AND the old-length prefix still hashes
    # to the previously recorded full hash ⇒ genuine append (a fixed-window
    # head hash would false-negative on files smaller than the window).
    lines: list[str]
    if (
        wm is not None
        and isinstance(wm.get("size"), int)
        and 0 < int(wm["size"]) < stat.st_size
        and hashlib.sha256(data[: int(wm["size"])]).hexdigest() == wm.get("full_hash")
    ):
        offset = int(wm["size"])
        # If the old prefix ended mid-line, align forward to the next
        # newline so the delta starts on a clean line boundary.
        if offset > 0 and data[offset - 1 : offset] != b"\n":
            nl = data.find(b"\n", offset)
            offset = nl + 1 if nl != -1 else offset
        lines = data[offset:].decode("utf-8", errors="replace").splitlines()
        summary["mode"] = "delta"
    else:
        lines = data.decode("utf-8", errors="replace").splitlines()
        summary["mode"] = "full"

    sampled = _sample_lines(lines)
    records = [_make_record(source_key, kind, i, text) for i, text in enumerate(sampled)]
    _append_records(records)

    recent = ([*recent, full_hash])[-FULL_HASH_MEMO:]
    watermarks[source_key] = {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "head_hash": _head_hash(data),
        "full_hash": full_hash,
        "recent_full_hashes": recent,
    }
    _save_watermarks(watermarks)

    summary["added"] = len(records)
    return summary


# ---------------------------------------------------------------------------
# Consumer groups (at-least-once)
# ---------------------------------------------------------------------------


def _load_groups() -> dict[str, str]:
    data = _load_json(_cursors_path(), {})
    groups = data.get("groups") if isinstance(data, dict) else None
    return groups if isinstance(groups, dict) else {}


def _save_groups(groups: dict[str, str]) -> None:
    data = _load_json(_cursors_path(), {})
    if not isinstance(data, dict):
        data = {}
    data["groups"] = groups
    _atomic_write_json(_cursors_path(), data)


def consume(group: str, limit: int = 50) -> list[dict[str, Any]]:
    """Records after *group*'s committed cursor (at-least-once)."""
    cursor = _load_groups().get(group)
    records = read_records()
    if cursor is None:
        return records[: max(1, limit)]
    ids = [r["id"] for r in records]
    try:
        start = ids.index(cursor) + 1
    except ValueError:
        start = 0
    return records[start : start + max(1, limit)]


def commit(group: str, last_id: str) -> None:
    """Advance *group*'s cursor to *last_id* (only after processing)."""
    groups = _load_groups()
    groups[group] = last_id
    _save_groups(groups)


__all__ = [
    "BATCH_CAP",
    "HEAD_BYTES",
    "commit",
    "consume",
    "ingest_file",
    "read_records",
]
