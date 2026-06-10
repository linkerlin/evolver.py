"""Local JSON/JSONL persistence for genes, capsules, events, candidates.

Equivalent to evolver/src/gep/assetStore.js.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from filelock import FileLock

from evolver.gep.content_hash import compute_asset_id, verify_asset_id
from evolver.gep.paths import get_bundled_gep_assets_dir, get_gep_assets_dir


def _sqlite_enabled() -> bool:
    return os.environ.get("EVOLVER_SQLITE_STORE", "").lower() in ("1", "true", "yes", "on")


def _safe_json_loads(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def read_json_if_exists(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return None
        return json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically via temp file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".tmp.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl_tail(path: Path, limit: int = 1000) -> list[dict]:
    if not path.exists():
        return []
    lines: list[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def read_jsonl_all(path: Path) -> list[dict]:
    return read_jsonl_tail(path, limit=1_000_000)


# --- Asset store paths ---


def genes_path() -> Path:
    return get_gep_assets_dir() / "genes.json"


def genes_seed_path() -> Path:
    return get_bundled_gep_assets_dir() / "genes.seed.json"


def capsules_path() -> Path:
    return get_gep_assets_dir() / "capsules.json"


def events_path() -> Path:
    return get_gep_assets_dir() / "events.jsonl"


def candidates_path() -> Path:
    return get_gep_assets_dir() / "candidates.jsonl"


def external_candidates_path() -> Path:
    return get_gep_assets_dir() / "external_candidates.jsonl"


def failed_capsules_path() -> Path:
    return get_gep_assets_dir() / "failed_capsules.json"


def pending_signals_path() -> Path:
    return get_gep_assets_dir() / "pending_signals.json"


# --- File lock ---

_LOCK_PATH: Path | None = None


def _lock_path() -> Path:
    global _LOCK_PATH
    if _LOCK_PATH is None:
        _LOCK_PATH = get_gep_assets_dir() / ".asset_store.lock"
        _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _LOCK_PATH


@contextmanager
def with_file_lock(timeout: float = 30.0) -> Iterator[None]:
    lock = FileLock(_lock_path(), timeout=timeout)
    with lock:
        yield


# --- Load / save genes ---


def _maybe_verify_asset(asset: dict) -> bool:
    asset_id = asset.get("asset_id")
    if not asset_id:
        return True
    return verify_asset_id(asset, asset_id)


def _ensure_asset_id(asset: dict) -> dict:
    if not asset.get("asset_id"):
        asset = dict(asset)
        asset["asset_id"] = compute_asset_id(asset)
    return asset


def load_genes() -> list[dict]:
    base = read_json_if_exists(genes_path()) or {}
    genes = list(base.get("genes", []))
    # Overlay genes.jsonl
    overlay_path = genes_path().with_suffix(".jsonl")
    for row in read_jsonl_all(overlay_path):
        if isinstance(row, dict) and row.get("id"):
            if not _maybe_verify_asset(row):
                continue
            # Replace by id or append
            for i, g in enumerate(genes):
                if g.get("id") == row["id"]:
                    genes[i] = row
                    break
            else:
                genes.append(row)
    # Seed fallback if empty
    if not genes:
        seed = read_json_if_exists(genes_seed_path()) or {}
        genes = list(seed.get("genes", []))
    return genes


def upsert_gene(gene: dict) -> None:
    gene = _ensure_asset_id(gene)
    with with_file_lock():
        append_jsonl(genes_path().with_suffix(".jsonl"), gene)


# --- Load / save capsules ---


def load_capsules() -> list[dict]:
    base = read_json_if_exists(capsules_path()) or {}
    capsules = list(base.get("capsules", []))
    overlay_path = capsules_path().with_suffix(".jsonl")
    for row in read_jsonl_all(overlay_path):
        if isinstance(row, dict) and row.get("id"):
            if not _maybe_verify_asset(row):
                continue
            for i, c in enumerate(capsules):
                if c.get("id") == row["id"]:
                    capsules[i] = row
                    break
            else:
                capsules.append(row)
    return capsules


def append_capsule(capsule: dict) -> None:
    capsule = _ensure_asset_id(capsule)
    with with_file_lock():
        append_jsonl(capsules_path().with_suffix(".jsonl"), capsule)


def upsert_capsule(capsule: dict) -> None:
    append_capsule(capsule)


# --- Events ---


def read_all_events() -> list[dict]:
    if _sqlite_enabled():
        from evolver.ops.sqlite_store import read_all_events as _sqlite_read
        return _sqlite_read()
    return read_jsonl_all(events_path())


def get_last_event_id() -> str | None:
    events = read_all_events()
    if not events:
        return None
    last = events[-1]
    return last.get("id") or last.get("event_id")


def append_event_jsonl(record: dict) -> None:
    if _sqlite_enabled():
        from evolver.ops.sqlite_store import append_event as _sqlite_append
        _sqlite_append(record)
        return
    with with_file_lock():
        append_jsonl(events_path(), record)


# --- Candidates ---


def append_candidate_jsonl(record: dict) -> None:
    with with_file_lock():
        append_jsonl(candidates_path(), record)


def append_external_candidate_jsonl(record: dict) -> None:
    with with_file_lock():
        append_jsonl(external_candidates_path(), record)


def read_recent_candidates(limit: int = 100) -> list[dict]:
    return read_jsonl_tail(candidates_path(), limit=limit)


def read_recent_external_candidates(limit: int = 100) -> list[dict]:
    return read_jsonl_tail(external_candidates_path(), limit=limit)


# --- Failed capsules ---


def append_failed_capsule(record: dict) -> None:
    with with_file_lock():
        path = failed_capsules_path()
        current = read_json_if_exists(path) or {"failed": []}
        current.setdefault("failed", []).append(record)
        atomic_write_json(path, current)


def read_recent_failed_capsules(limit: int = 100) -> list[dict]:
    data = read_json_if_exists(failed_capsules_path()) or {}
    return list(data.get("failed", []))[-limit:]


# --- Pending signals ---


def consume_pending_signals() -> list[str]:
    """Read and clear pending_signals.json in one go."""
    with with_file_lock():
        path = pending_signals_path()
        data = read_json_if_exists(path) or {"signals": []}
        signals = list(data.get("signals", []))
        if signals:
            atomic_write_json(path, {"signals": [], "note": ""})
        return signals


# --- Validation command helper ---


def build_validation_cmd(cmd: str, project_dir: Path | str) -> list[str]:
    """Build a safe validation command argv."""
    import shlex

    parts = shlex.split(cmd)
    if not parts:
        return []
    # Restrict to known safe executables
    allowed = {"node", "python", "python3", "npm", "uv", "git", "pytest", "ruff", "mypy"}
    if parts[0] not in allowed:
        return []
    return parts
