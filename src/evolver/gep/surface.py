"""Surface snapshots — stable editable-surface baselines.

Methodology inspired by Self-Harness (arXiv:2606.09498, ``EditableSurface``
three-view model). No Node.js equivalent; evolver.py self-research addition
(Sprint A2).

A *surface* is the set of editable files the harness is made of. The
three-view decoupling keeps the proposer anchored to a stable baseline even
as the eval surface advances:

* **baseline surface** — captured at cycle start (the stable parent the
  proposer diffs against),
* **eval surface** — the currently-evaluated state (advances with the branch),
* **proposer surface** — what the proposer sees (= baseline; never drifts).

This module captures content-addressed fingerprints (path → sha256) so any
two snapshots can be compared cheaply via :func:`surface_delta`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

_SURFACE_FORMAT = "evolver.surface_snapshot.v0"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_files(paths: list[Path]) -> dict[str, str]:
    """Map relative path → sha256 content hash for *paths*.

    Missing/unreadable files are recorded as ``"<missing>"`` so snapshots stay
    comparable even when a file temporarily disappears.
    """
    fingerprints: dict[str, str] = {}
    for path in paths:
        rel = path.as_posix()
        try:
            fingerprints[rel] = _file_sha256(path)
        except OSError:
            fingerprints[rel] = "<missing>"
    return fingerprints


def _snapshot_id(files: dict[str, str]) -> str:
    payload = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class SurfaceSnapshot(BaseModel):
    """A content-addressed fingerprint of the editable surface."""

    model_config = ConfigDict(extra="forbid")
    files: dict[str, str] = {}
    snapshot_id: str = ""
    format: str = _SURFACE_FORMAT

    def compute_id(self) -> str:
        """(Re)compute the content id from ``files``."""
        return _snapshot_id(self.files)


def capture_surface(paths: list[Path]) -> SurfaceSnapshot:
    """Capture a snapshot of *paths* (relative names from the paths as given)."""
    files = fingerprint_files(paths)
    snapshot = SurfaceSnapshot(files=files)
    snapshot.snapshot_id = snapshot.compute_id()
    return snapshot


def save_snapshot(snapshot: SurfaceSnapshot, path: Path) -> None:
    """Persist a snapshot to *path* (atomic)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(snapshot.model_dump_json(indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_snapshot(path: Path) -> SurfaceSnapshot | None:
    """Read a snapshot back; ``None`` when missing/corrupt."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return SurfaceSnapshot.model_validate(payload)


def surface_delta(
    base: SurfaceSnapshot,
    current: SurfaceSnapshot,
) -> dict[str, Any]:
    """Files added / removed / changed between *base* and *current*."""
    base_files = base.files
    current_files = current.files
    added = sorted(set(current_files) - set(base_files))
    removed = sorted(set(base_files) - set(current_files))
    changed = sorted(
        rel
        for rel in set(base_files) & set(current_files)
        if base_files[rel] != current_files[rel]
    )
    return {"added": added, "removed": removed, "changed": changed}


__all__ = [
    "SurfaceSnapshot",
    "capture_surface",
    "fingerprint_files",
    "load_snapshot",
    "save_snapshot",
    "surface_delta",
]
