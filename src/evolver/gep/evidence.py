"""Immutable evidence layer (S28.1) — per-run scene snapshots.

No Node.js equivalent; evolver.py addition.

Wikiskill honesty contract, adapted: the raw evidence of a solidify run
(validation results, blast radius, diff snapshot, verdicts) is written ONCE
into ``<GEP_ASSETS_DIR>/evidence/<run_id>/``. Writing the same file twice
raises :class:`FileExistsError` — evidence is immutable by architecture, not
by convention. Replaying a historical cycle must reproduce byte-identical
files.

This complements ``events.jsonl`` (the append-only ledger): evidence keeps
the FULL scene per run, grouped for post-mortem reads.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from evolver.gep.paths import get_gep_assets_dir

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def evidence_dir(run_id: str) -> Path:
    if not run_id or not _SAFE_ID_RE.match(run_id):
        raise ValueError(f"invalid run_id for evidence: {run_id!r}")
    return get_gep_assets_dir() / "evidence" / run_id


def save_evidence(run_id: str, kind: str, payload: Any) -> Path:
    """Write one evidence file. Immutability: an existing file is NEVER
    overwritten — ``FileExistsError`` is the honest signal that this run's
    evidence was already captured (a second solidify of the same run must not
    silently rewrite history)."""
    if not kind or not _SAFE_ID_RE.match(kind):
        raise ValueError(f"invalid evidence kind: {kind!r}")
    directory = evidence_dir(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{kind}.json"
    if path.exists():
        raise FileExistsError(f"evidence is immutable: {path} already exists")
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def load_evidence(run_id: str, kind: str) -> Any:
    path = evidence_dir(run_id) / f"{kind}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


__all__ = ["evidence_dir", "load_evidence", "save_evidence"]
