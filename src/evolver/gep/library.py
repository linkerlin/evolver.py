"""Content-addressed library snapshots — the content dimension's Parent.

EvoOntology's store keeps ``active.json`` as a bare pointer and every
version under ``versions/<v>/``. Three rules make it trustworthy:

1. **Publish never overwrites.** Writing a version whose id already exists
   with different content is an error, not a silent replacement.
2. **Only publishing moves ``active``.** Loading a version by id is a read;
   it must never have the side effect of making that version current.
3. **The Parent is frozen at session open.** The run record remembers which
   version it started from, so an Accept published mid-comparison cannot
   quietly become the thing being compared against.

evolver needs all three for charter §5.4: a content-dimension candidate is
consulted as a library snapshot, and *during the comparison ``active`` still
points at the Parent*. Otherwise the candidate compares against itself and
every mutation looks like an improvement.

Run-state only — the library lives under the evolution dir, never in the
product repo (AGENTS.md: 运行态不进产品 git).

Harvested from EvoOntology ``ontology/store.py``; no Node.js equivalent.
Charter 2026-09-26.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from evolver.gep.asset_store import atomic_write_json, with_file_lock
from evolver.gep.content_hash import canonicalize, compute_asset_id
from evolver.gep.paths import get_evolution_dir

LIBRARY_DIRNAME: Final = "library"
ACTIVE_FILENAME: Final = "active.json"
VERSIONS_DIRNAME: Final = "versions"
SNAPSHOT_FILENAME: Final = "snapshot.json"
LIBRARY_FORMAT: Final = "evolver.library.v0"


class SnapshotConflictError(RuntimeError):
    """Raised when a snapshot id already exists with different content.

    Publish never overwrites: two different libraries must never share an
    id, because the id is what ``active`` and every run record cite.
    """


def library_dir() -> Path:
    return get_evolution_dir() / LIBRARY_DIRNAME


def active_path() -> Path:
    return library_dir() / ACTIVE_FILENAME


def versions_dir() -> Path:
    return library_dir() / VERSIONS_DIRNAME


def snapshot_id(payload: dict[str, Any]) -> str:
    """Content address of a snapshot — same bytes, same id, always."""
    return compute_asset_id(payload)


def version_path(snap: str) -> Path:
    """Path of one snapshot's payload file.

    The id is ``sha256:<hex>`` and Windows refuses a colon in a path
    component, so the directory name escapes it. The id itself stays intact
    everywhere else — in ``active.json``, in run records, in the API — so
    the escaping is a storage detail, not a second identity.
    """
    return versions_dir() / str(snap).replace(":", "_", 1) / SNAPSHOT_FILENAME


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def active_snapshot_id() -> str | None:
    """The id ``active`` points at, or ``None`` when nothing is published."""
    path = active_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("snapshot")
    return str(value) if value else None


def load_active() -> dict[str, Any] | None:
    """The published snapshot's payload, or ``None``. Read-only by design."""
    snap = active_snapshot_id()
    if snap is None:
        return None
    return load_version(snap)


def load_version(snap: str) -> dict[str, Any] | None:
    """Load one snapshot by id. Explicit loads never touch ``active`` —
    during a comparison that is the whole point: the candidate may be read
    without becoming the thing the Parent is measured against."""
    path = version_path(snap)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def save_version(payload: dict[str, Any]) -> dict[str, Any]:
    """Store one snapshot under its content address.

    Idempotent for identical content (same id, same bytes). Different bytes
    under an existing id raise :class:`SnapshotConflictError` — publishing
    must never overwrite, or every older citation of that id silently
    changes meaning.
    """
    if not isinstance(payload, dict):
        raise SnapshotConflictError("a library snapshot must be a JSON object")
    snap = snapshot_id(payload)
    target = version_path(snap)
    if target.exists():
        existing = load_version(snap)
        if canonicalize(existing) != canonicalize(payload):
            raise SnapshotConflictError(
                f"snapshot {snap} already exists with different content — publish never overwrites"
            )
        return {"ok": True, "reason": "already_stored", "snapshot": snap, "path": str(target)}

    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, payload)
    return {"ok": True, "reason": "stored", "snapshot": snap, "path": str(target)}


def _set_active(snap: str, *, session_id: str = "", run_id: str = "") -> dict[str, Any]:
    """Move the ``active`` pointer. Private on purpose: the only caller is
    :func:`publish`, so no other code path can make a version current."""
    path = active_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": LIBRARY_FORMAT,
        "snapshot": snap,
        "session_id": session_id,
        "run_id": run_id,
    }
    atomic_write_json(path, payload)
    return payload


def publish(
    payload: dict[str, Any],
    *,
    session_id: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    """Store a snapshot and make it the active library. Accept-only.

    Returns ``{"ok", "snapshot", "previous", "path"}``. The previous active
    id is returned so the caller can record the Parent line it just moved.
    """
    with with_file_lock(target_path=library_dir()):
        previous = active_snapshot_id()
        stored = save_version(payload)
        snap = str(stored["snapshot"])
        _set_active(snap, session_id=session_id, run_id=run_id)
    return {
        "ok": True,
        "reason": "published",
        "snapshot": snap,
        "previous": previous,
        "path": str(active_path()),
    }


def snapshot_of(payload: dict[str, Any] | None) -> str | None:
    """Convenience for callers holding a payload rather than an id."""
    if not isinstance(payload, dict):
        return None
    return snapshot_id(payload)


__all__ = [
    "ACTIVE_FILENAME",
    "LIBRARY_DIRNAME",
    "LIBRARY_FORMAT",
    "SNAPSHOT_FILENAME",
    "VERSIONS_DIRNAME",
    "SnapshotConflictError",
    "active_path",
    "active_snapshot_id",
    "library_dir",
    "load_active",
    "load_version",
    "publish",
    "save_version",
    "snapshot_id",
    "snapshot_of",
    "version_path",
    "versions_dir",
]
