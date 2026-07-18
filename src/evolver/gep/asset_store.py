"""Local JSON/JSONL persistence for genes, capsules, events, candidates.

Equivalent to evolver/src/gep/assetStore.js.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from filelock import FileLock

from evolver.gep.content_hash import compute_asset_id, verify_asset_id
from evolver.gep.paths import get_bundled_gep_assets_dir, get_gep_assets_dir


def _sqlite_enabled() -> bool:
    return os.environ.get("EVOLVER_SQLITE_STORE", "").lower() in ("1", "true", "yes", "on")


def _safe_json_loads(raw: str) -> Any:
    try:
        return cast(dict[str, Any], json.loads(raw))
    except json.JSONDecodeError:
        return None


def read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return None
        return cast(dict[str, Any], json.loads(raw))
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


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


_LARGE_JSONL_BYTES = 1024 * 1024  # 1 MiB — switch to tail-only read


def read_jsonl_tail(path: Path, limit: int = 1000) -> list[dict[str, Any]]:
    """Read last *limit* JSONL objects; for files >1MiB only scan the tail."""
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size == 0:
        return []

    try:
        if size < _LARGE_JSONL_BYTES:
            raw = path.read_text(encoding="utf-8", errors="replace")
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        else:
            # Large file: only read the tail to avoid OOM (Node parity).
            chunk_size = min(size, max(limit, 1) * 4096)
            with path.open("rb") as handle:
                handle.seek(size - chunk_size)
                buf = handle.read(chunk_size)
            text = buf.decode("utf-8", errors="replace")
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            # Drop first partial line when we mid-seeked into a record.
            if size > chunk_size and lines:
                lines = lines[1:]
    except OSError:
        return []

    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            out.append(parsed)
    return out


def read_jsonl_all(path: Path) -> list[dict[str, Any]]:
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


def _default_lock_path() -> Path:
    global _LOCK_PATH
    if _LOCK_PATH is None:
        _LOCK_PATH = get_gep_assets_dir() / ".asset_store.lock"
        _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _LOCK_PATH


def _lock_path_for(target_path: Path | str | None = None) -> Path:
    """Resolve lock file path (Node: lock adjacent to the critical-section target)."""
    if target_path is None:
        return _default_lock_path()
    target = Path(target_path)
    # Prefer sibling ``.lock`` next to the target file/dir.
    lock = Path(str(target) + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    return lock


@contextmanager
def with_file_lock(
    timeout: float = 30.0,
    target_path: Path | str | None = None,
) -> Iterator[None]:
    """Serialize critical sections; *target_path* scopes the lock file (issue #451)."""
    lock = FileLock(str(_lock_path_for(target_path)), timeout=timeout)
    with lock:
        yield


# --- Load / save genes ---


def _maybe_verify_asset(asset: dict[str, Any]) -> bool:
    asset_id = asset.get("asset_id")
    if not asset_id:
        return True
    return verify_asset_id(asset, asset_id)


def _ensure_asset_id(asset: dict[str, Any]) -> dict[str, Any]:
    if not asset.get("asset_id"):
        asset = dict(asset)
        asset["asset_id"] = compute_asset_id(asset)
    return asset


def _merge_json_jsonl(
    base_items: list[dict[str, Any]],
    overlay_path: Path,
    *,
    type_name: str | None = None,
    verify: bool = True,
) -> list[dict[str, Any]]:
    """Combine base JSON array with JSONL overlay (JSONL wins by id).

    Does **not** pass items through schema factories — on-disk shape is
    preserved so content hashes remain valid (PR #25 regression).
    """
    by_id: dict[str, dict[str, Any]] = {}
    for item in base_items:
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item["id"])] = item
    for row in read_jsonl_all(overlay_path):
        if not isinstance(row, dict) or not row.get("id"):
            continue
        # Accept missing type for legacy rows; skip wrong type when present.
        if (
            type_name
            and row.get("type") is not None
            and row.get("type") != type_name
        ):
            continue
        if verify and not _maybe_verify_asset(row):
            continue
        by_id[str(row["id"])] = row
    return list(by_id.values())


def ensure_genes_seeded() -> None:
    """Copy bundled genes.seed.json → genes.json on first run only.

    Once genes.json exists it is user-owned and never re-seeded (upgrade-safe).
    """
    target = genes_path()
    if target.exists():
        return
    seed = genes_seed_path()
    if not seed.exists():
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(seed.read_bytes())
    except OSError:
        pass


def ensure_asset_files() -> None:
    """Create the GEP asset-store skeleton if missing (Node ensureAssetFiles)."""
    directory = get_gep_assets_dir()
    directory.mkdir(parents=True, exist_ok=True)
    ensure_genes_seeded()
    defaults: list[tuple[Path, str]] = [
        (genes_path(), ""),  # seeded above when possible
        (capsules_path(), json.dumps({"version": 1, "capsules": []}, indent=2) + "\n"),
        (genes_path().with_suffix(".jsonl"), ""),
        (events_path(), ""),
        (candidates_path(), ""),
        (
            failed_capsules_path(),
            json.dumps({"version": 1, "failed": []}, indent=2) + "\n",
        ),
    ]
    for path, content in defaults:
        if path.exists():
            continue
        try:
            if content:
                path.write_text(content, encoding="utf-8")
            else:
                path.touch()
        except OSError:
            pass


def load_genes(*, seed: bool = True) -> list[dict[str, Any]]:
    """Load genes (JSON + JSONL overlay). *seed* controls first-run seeding."""
    if seed:
        ensure_genes_seeded()
    base = read_json_if_exists(genes_path()) or {}
    genes = list(base.get("genes", []))
    genes = _merge_json_jsonl(
        genes, genes_path().with_suffix(".jsonl"), type_name="Gene", verify=True
    )
    # In-memory seed fallback when nothing is on disk (read-only / empty install).
    if not genes:
        seed_data = read_json_if_exists(genes_seed_path()) or {}
        genes = list(seed_data.get("genes", []))
    return genes


def load_genes_read_only() -> list[dict[str, Any]]:
    """Load genes without seeding or creating asset-store directories."""
    return load_genes(seed=False)


def upsert_gene(gene: dict[str, Any]) -> None:
    gene = _ensure_asset_id(gene)
    target = genes_path()
    with with_file_lock(target_path=target):
        append_jsonl(target.with_suffix(".jsonl"), gene)


# --- Load / save capsules ---


def load_capsules() -> list[dict[str, Any]]:
    base = read_json_if_exists(capsules_path()) or {}
    capsules = list(base.get("capsules", []))
    return _merge_json_jsonl(
        capsules, capsules_path().with_suffix(".jsonl"), type_name="Capsule", verify=True
    )


def load_capsules_read_only() -> list[dict[str, Any]]:
    """Load capsules without creating directories or default files."""
    return load_capsules()


def append_capsule(capsule: dict[str, Any]) -> None:
    capsule = _ensure_asset_id(capsule)
    target = capsules_path()
    with with_file_lock(target_path=target):
        append_jsonl(target.with_suffix(".jsonl"), capsule)


def upsert_capsule(capsule: dict[str, Any]) -> None:
    append_capsule(capsule)


# --- Events ---


def read_all_events() -> list[dict[str, Any]]:
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


def append_event_jsonl(record: dict[str, Any]) -> None:
    if _sqlite_enabled():
        from evolver.ops.sqlite_store import append_event as _sqlite_append

        _sqlite_append(record)
        return
    with with_file_lock(target_path=events_path()):
        append_jsonl(events_path(), record)


# --- Candidates ---


def append_candidate_jsonl(record: dict[str, Any]) -> None:
    with with_file_lock(target_path=candidates_path()):
        append_jsonl(candidates_path(), record)


def append_external_candidate_jsonl(record: dict[str, Any]) -> None:
    with with_file_lock(target_path=external_candidates_path()):
        append_jsonl(external_candidates_path(), record)


def read_recent_candidates(limit: int = 20) -> list[dict[str, Any]]:
    """Return the last *limit* candidates (default 20 — Node parity)."""
    return read_jsonl_tail(candidates_path(), limit=limit)


def read_recent_external_candidates(limit: int = 50) -> list[dict[str, Any]]:
    return read_jsonl_tail(external_candidates_path(), limit=limit)


# --- Failed capsules ---


def append_failed_capsule(record: dict[str, Any]) -> None:
    path = failed_capsules_path()
    with with_file_lock(target_path=path):
        current = read_json_if_exists(path) or {"failed": []}
        current.setdefault("failed", []).append(record)
        atomic_write_json(path, current)


def read_recent_failed_capsules(limit: int = 100) -> list[dict[str, Any]]:
    data = read_json_if_exists(failed_capsules_path()) or {}
    return list(data.get("failed", []))[-limit:]


# --- Pending signals ---


def consume_pending_signals() -> list[str]:
    """Read and clear pending_signals.json in one go."""
    path = pending_signals_path()
    with with_file_lock(target_path=path):
        data = read_json_if_exists(path) or {"signals": []}
        signals = list(data.get("signals", []))
        if signals:
            atomic_write_json(path, {"signals": [], "note": ""})
        return signals


def append_pending_signals(new_signals: list[str]) -> None:
    """Append autopoiesis-derived signals without clearing existing entries."""
    if not new_signals:
        return
    path = pending_signals_path()
    with with_file_lock(target_path=path):
        data = read_json_if_exists(path) or {"signals": []}
        existing = list(data.get("signals", []))
        for signal in new_signals:
            if signal not in existing:
                existing.append(signal)
        atomic_write_json(path, {"signals": existing, "note": data.get("note", "")})


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
