"""Cross-component diagnostic ledger — P2-7 (RSI 演进对照.md, round-74).

DEBUG.md's four-section entries (症状/根因/修复/经验) are exactly the
"intervention hypothesis records" the RSI paper asks for — but they are
human prose, unaggregatable by machine. This ledger structures them:

    {symptom_signature, suspect_components, hypothesis, conclusion,
    blamed_component}

Written automatically when a solidify validation failure opens an entry;
the host backfills the attribution after the fix lands. Entries are keyed
by symptom signature so a recurrence can retrieve prior attributions
without a human re-reading DEBUG.md. DEBUG.md itself stays the
human-readable projection (generated prose), never replaced.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final

from evolver.gep.asset_store import with_file_lock
from evolver.gep.paths import get_evolution_dir

#: Minimum structural similarity for a signature match (trigram Jaccard).
SIGNATURE_MATCH_THRESHOLD: Final = 0.45


def ledger_path() -> Path:

    return get_evolution_dir() / "diagnostic_ledger.jsonl"


def symptom_signature(text: str) -> str:
    """Stable short hash of a failure's most distinctive line.

    Uses the last non-empty line of the failure output (pytest error
    summaries, mypy diagnostics) — stable across runs of the same defect,
    sensitive to different defects.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    tail = lines[-1]
    # Drop volatile suffixes (counts, paths, durations) before hashing.
    for volatile in (" passed", " failed", " in ", "s"):
        idx = tail.rfind(volatile)
        if idx > 0:
            tail = tail[:idx]
            break
    return hashlib.sha256(tail.encode("utf-8")).hexdigest()[:12]


def trigrams(text: str) -> set[str]:
    text = text.lower()
    if len(text) < 3:
        return {text}
    return {text[i : i + 3] for i in range(len(text) - 2)}


def signature_similarity(a: str, b: str) -> float:
    """Jaccard similarity of character trigrams of the two signatures'
    source tails is not recoverable from hashes alone, so similarity is
    computed on the stored signature strings directly (stable prefixes)."""
    if not a or not b:
        return 0.0
    ga, gb = trigrams(a), trigrams(b)
    union = ga | gb
    if not union:
        return 0.0
    return len(ga & gb) / len(union)


def open_entry(
    *,
    run_id: str,
    event_id: str,
    symptom_text: str,
    suspect_components: list[str],
) -> dict[str, Any] | None:
    """Open a diagnostic entry for a validation failure (auto from solidify).

    Recurrence check: if an existing entry's signature matches the new
    symptom, increment its recurrence count instead of appending a duplicate
    — recurrence is the retrieval signal P1-4's evidence pack consumes.
    """
    signature = symptom_signature(symptom_text)
    if not signature:
        return None
    entry = {
        "type": "DiagnosticEntry",
        "signature": signature,
        "run_id": run_id,
        "event_id": event_id,
        "symptom_tail": "\n".join(symptom_text.splitlines()[-3:])[:400],
        "suspect_components": suspect_components,
        "hypothesis": "",  # host backfills after the fix
        "blamed_component": "",  # host backfills: the component the fix touched
        "resolved": False,
        "recurrence": 0,
    }
    ledger = ledger_path()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with with_file_lock(target_path=ledger):
        existing = _load_entries(ledger)
        for row in existing:
            sim = signature_similarity(row.get("signature", ""), signature)
            if sim >= SIGNATURE_MATCH_THRESHOLD:
                row["recurrence"] = int(row.get("recurrence", 0)) + 1
                entry = row
                break
        else:
            existing.append(entry)
        _save_entries(ledger, existing)
    return entry


def backfill_attribution(
    signature: str,
    *,
    hypothesis: str,
    blamed_component: str,
) -> dict[str, Any] | None:
    """Host-side backfill after the fix lands (P2-7 conclusion field)."""
    ledger = ledger_path()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with with_file_lock(target_path=ledger):
        entries = _load_entries(ledger)
        for row in entries:
            if row.get("signature") == signature:
                row["hypothesis"] = hypothesis[:500]
                row["blamed_component"] = blamed_component[:200]
                row["resolved"] = True
                _save_entries(ledger, entries)
                return row
    return None


def _load_entries(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("type") == "DiagnosticEntry":
            rows.append(row)
    return rows


def _save_entries(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
        encoding="utf-8",
    )
    tmp.replace(path)


def find_similar(
    symptom_text: str, *, min_similarity: float = SIGNATURE_MATCH_THRESHOLD
) -> list[dict[str, Any]]:
    """Retrieve historical entries whose signature matches this symptom."""
    signature = symptom_signature(symptom_text)
    if not signature:
        return []
    out: list[dict[str, Any]] = []
    for row in _load_entries(ledger_path()):
        sim = signature_similarity(row.get("signature", ""), signature)
        if sim >= min_similarity:
            out.append({**row, "similarity": round(sim, 3)})
    out.sort(key=lambda r: -float(r.get("similarity", 0)))
    return out


__all__ = [
    "SIGNATURE_MATCH_THRESHOLD",
    "backfill_attribution",
    "find_similar",
    "ledger_path",
    "open_entry",
    "signature_similarity",
    "symptom_signature",
]
