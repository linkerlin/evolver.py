"""Portable `.gepx` archive — export/import workspace GEP assets.

Equivalent to Node's ``evolver/src/gep/portable.js``.

Format: gzip-tar containing:
- ``genes.json`` + ``genes.jsonl``
- ``capsules.json`` + ``capsules.jsonl``
- ``events.jsonl`` (recent 1000)
- ``memory_graph.jsonl`` (recent 1000)
- ``manifest.json`` (metadata, version, SHA-256 checksums)
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import tarfile
import time
from io import BytesIO
from pathlib import Path
from typing import Any

from .paths import get_memory_dir

logger = logging.getLogger(__name__)

MANIFEST_VERSION = "1.0"
MAX_EVENTS = 1000
MAX_MEMORY = 1000


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    """Read up to *limit* most recent lines from a JSONL file."""
    if not path.exists():
        return []
    lines: list[str] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)
    # Take most recent
    return [json.loads(ln) for ln in lines[-limit:]]


def _file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def export_gepx(output_path: Path) -> Path:
    """Export workspace GEP assets to a ``.gepx`` file."""
    mem = get_memory_dir()
    buf = BytesIO()

    entries: dict[str, bytes] = {}

    # Genes
    genes_json = mem / "genes.json"
    if genes_json.exists():
        entries["genes.json"] = genes_json.read_bytes()
    genes_jsonl = mem / "genes.jsonl"
    if genes_jsonl.exists():
        entries["genes.jsonl"] = genes_jsonl.read_bytes()

    # Capsules
    capsules_json = mem / "capsules.json"
    if capsules_json.exists():
        entries["capsules.json"] = capsules_json.read_bytes()
    capsules_jsonl = mem / "capsules.jsonl"
    if capsules_jsonl.exists():
        entries["capsules.jsonl"] = capsules_jsonl.read_bytes()

    # Recent events
    events = _read_jsonl(mem / "events.jsonl", MAX_EVENTS)
    events_bytes = "\n".join(json.dumps(e, ensure_ascii=False) for e in events).encode("utf-8")
    entries["events.jsonl"] = events_bytes

    # Recent memory graph
    memgraph = _read_jsonl(mem / "memory_graph.jsonl", MAX_MEMORY)
    memgraph_bytes = "\n".join(json.dumps(e, ensure_ascii=False) for e in memgraph).encode("utf-8")
    entries["memory_graph.jsonl"] = memgraph_bytes

    # Manifest
    manifest: dict[str, Any] = {
        "version": MANIFEST_VERSION,
        "created_at": time.time(),
        "files": {},
    }
    for name, data in entries.items():
        manifest["files"][name] = _file_hash(data)

    manifest_bytes = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
    entries["manifest.json"] = manifest_bytes

    # Build tar.gz
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = time.time()
            tf.addfile(info, BytesIO(data))

    output_path.write_bytes(buf.getvalue())
    logger.info("[Portable] Exported %d files to %s", len(entries), output_path)
    return output_path


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


class ImportError(Exception):
    pass


def import_gepx(path: Path, *, merge: bool = True) -> dict[str, Any]:
    """Import a ``.gepx`` archive into the workspace memory directory.

    If *merge* is ``True`` (default), existing entries are preserved and
    newer timestamps win. If ``False``, the archive overwrites existing files.
    """
    mem = get_memory_dir()
    if not path.exists():
        raise ImportError(f"Archive not found: {path}")

    with tarfile.open(path, "r:gz") as tf:
        names = tf.getnames()
        if "manifest.json" not in names:
            raise ImportError("Missing manifest.json in archive")

        manifest_bytes = tf.extractfile("manifest.json").read()
        manifest = json.loads(manifest_bytes)

        # Verify checksums
        for name, expected_hash in manifest.get("files", {}).items():
            if name == "manifest.json":
                continue
            member = tf.getmember(name)
            data = tf.extractfile(name).read()
            actual = _file_hash(data)
            if actual != expected_hash:
                raise ImportError(f"Checksum mismatch for {name}: expected {expected_hash[:16]}… got {actual[:16]}…")

        imported: dict[str, Any] = {"files": [], "merged": merge}
        for name in names:
            if name == "manifest.json":
                continue
            data = tf.extractfile(name).read()
            dest = mem / name

            if name.endswith(".jsonl") and merge and dest.exists():
                # Merge JSONL: timestamp-priority dedup
                _merge_jsonl(dest, data)
            else:
                tmp = dest.with_suffix(".tmp")
                tmp.write_bytes(data)
                tmp.replace(dest)

            imported["files"].append(name)
            logger.info("[Portable] Imported %s", name)

    logger.info("[Portable] Import complete from %s", path)
    return imported


def _merge_jsonl(dest: Path, new_data: bytes) -> None:
    """Merge JSONL lines from *new_data* into *dest*, keeping the latest
    by ``timestamp`` field."""
    existing = _read_jsonl(dest, limit=1_000_000)
    existing_by_id: dict[str, dict[str, Any]] = {}
    for row in existing:
        key = row.get("id") or row.get("gene_id") or row.get("capsule_id") or json.dumps(row, sort_keys=True)
        existing_by_id[key] = row

    for line in new_data.decode("utf-8").strip().splitlines():
        row = json.loads(line)
        key = row.get("id") or row.get("gene_id") or row.get("capsule_id") or json.dumps(row, sort_keys=True)
        old = existing_by_id.get(key)
        if old is None or row.get("timestamp", 0) > old.get("timestamp", 0):
            existing_by_id[key] = row

    merged = sorted(existing_by_id.values(), key=lambda r: r.get("timestamp", 0))
    tmp = dest.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for row in merged:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(dest)
