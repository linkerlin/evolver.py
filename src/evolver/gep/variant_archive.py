"""Variant archive — DGM rejected-but-retained candidates (RSI P1-3, round-40).

Methodology: Darwin Gödel Machine (变体档案 + 亲代选择). No direct Node.js
equivalent; evolver.py self-research addition (RSI演进对照.md P1-3 方案 3/4).

Every round used to be a single-candidate greedy search: a rejected mutation's
novelty fingerprint was archived but nothing could re-select it — no home for
"weak now, strong later". This module upgrades the dormant ``candidates.jsonl``
into a variant archive:

* :func:`classify_rejection` — environmental (timeout / OSError class) vs
  semantic rejection, judged where the stage stderr still lives (the solidify
  process; the persisted event slims it away).
* :func:`variant_entry` — archive entry shape carrying a replayable
  ``unified_diff`` (consumable by :func:`apply_variant` /
  ``evolver variants re-dispatch``; the S29 proposal channel's edit ops are
  append/replace/insert_after and take no diffs — round-44 correction of
  the round-40 claim).
* :func:`record_variant` — append to ``candidates.jsonl`` (revives the
  existing store API).
* :func:`re_dispatchable_variants` — pure predicate: an entry is
  re-dispatchable iff it was environmentally rejected, its signal family
  recurs, and its fingerprint has not been superseded by a later success.

The K=2 parallel-worktree half of P1-3 (population dispatch + dual
validation, touches frozen solidify semantics) lands separately with an
anchor epoch bump; this half only ADDS an archive beside the rejection flow.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Final

from evolver.gep.asset_store import append_candidate_jsonl, candidates_path
from evolver.gep.evidence_pack import _attempt_digest

logger = logging.getLogger(__name__)

#: Stage-output markers that identify an ENVIRONMENTAL rejection — the
#: mutation never got a fair semantic judgement (host overload, missing
#: tool). Everything else that fails a stage is semantic by default.
ENVIRONMENTAL_MARKERS: Final[tuple[str, ...]] = (
    "timed out",
    "timeoutexpired",
    "oserror",
    "no such file or directory",
)


def _stages(validation_result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(validation_result, dict):
        return []
    for key in ("results", "commands"):
        stages = validation_result.get(key)
        if isinstance(stages, list):
            return [s for s in stages if isinstance(s, dict)]
    return []


def classify_rejection(validation_result: dict[str, Any] | None) -> str | None:
    """Classify a failed validation as ``environmental``/``semantic``/``None``.

    ``None`` = validation never ran (nothing to classify). Environmental
    requires at least one failed stage whose output carries an
    environment-class marker; the round-28 host-overload timeout and the
    round-35 soak-route failure are the observed classes.
    """
    stages = _stages(validation_result)
    failed = [s for s in stages if not s.get("ok")]
    if not failed:
        return None
    for stage in failed:
        blob = f"{stage.get('stderr') or ''}{stage.get('stdout') or ''}".lower()
        if any(marker in blob for marker in ENVIRONMENTAL_MARKERS):
            return "environmental"
    return "semantic"


def _heads(signals: list[str] | tuple[str, ...] | None) -> list[str]:
    out: set[str] = set()
    for item in signals or []:
        text = str(item).strip()
        if text:
            out.add(text.split(":", 1)[0])
    return sorted(out)


def variant_entry(
    event: dict[str, Any],
    rejection_class: str | None,
) -> dict[str, Any] | None:
    """Shape a failed event into an archive entry; ``None`` when nothing to file.

    Entries without an edit fingerprint carry nothing replayable — the
    archive is for near-miss EDITS, not for every rejection bookkeeping row.
    """
    fingerprint = _attempt_digest(event)
    if not fingerprint:
        return None
    diff = str(event.get("diff_snapshot") or "")
    entry: dict[str, Any] = {
        "type": "VariantArchiveEntry",
        "variant_id": f"var_{fingerprint}",
        "run_id": event.get("run_id"),
        "gene_id": event.get("gene_id"),
        "signal_heads": _heads(event.get("signals")),
        "rejection_class": rejection_class,
        "fingerprint": fingerprint,
        "rejection_reason": str(event.get("outcome", {}).get("error") or "")[:200],
        "recorded_at": event.get("timestamp"),
    }
    if diff:
        entry["replay"] = {"kind": "unified_diff", "diff": diff}
    return entry


def record_variant(
    event: dict[str, Any],
    rejection_class: str | None,
) -> dict[str, Any] | None:
    """Append an archive entry to ``candidates.jsonl`` (revives the store API).

    Never raises for missing payload (returns ``None``); store I/O errors
    propagate — the caller wraps this in a guard so archive trouble can never
    break the rejection flow itself.
    """
    entry = variant_entry(event, rejection_class)
    if entry is None:
        return None
    append_candidate_jsonl(entry)
    return entry


def load_variants(path: Path | None = None) -> list[dict[str, Any]]:
    """Read archive entries (missing file → empty; malformed lines skipped)."""
    target = path or candidates_path()
    if not target.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("type") == "VariantArchiveEntry":
            entries.append(row)
    return entries


def re_dispatchable_variants(
    entries: list[dict[str, Any]],
    current_signals: list[str] | tuple[str, ...] | None,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Entries eligible for re-dispatch under the CURRENT signal family.

    Eligibility (DGM 暂弱变体可成垫脚石, mechanically bounded):

    1. environmentally rejected — the edit never got a semantic verdict
       (round-35 shape: environment repaired later, same edit green);
    2. signal-family overlap with the current dispatch's heads;
    3. fingerprint not superseded — no LATER success carries the same edit
       digest (it already landed; the archive row is history).

    Semantically rejected entries stay archived but are not auto-eligible:
    their blocker is a real defect, and "what changed since" is not yet a
    mechanical fact (future work with the K=2 half).
    """
    current = set(_heads(current_signals))
    if not current:
        return []
    superseded: set[str] = set()
    for ev in events:
        if (ev.get("outcome") or {}).get("status") == "success":
            digest = _attempt_digest(ev)
            if digest:
                superseded.add(digest)
    out = []
    for entry in entries:
        if entry.get("rejection_class") != "environmental":
            continue
        heads = set(entry.get("signal_heads") or [])
        if not heads & current:
            continue
        if entry.get("fingerprint") in superseded:
            continue
        out.append(entry)
    return out


def apply_variant(entry: dict[str, Any], cwd: Path) -> dict[str, Any]:
    """Mechanically re-apply an archived variant's diff (round-44).

    ``git apply --check`` first: a diff that no longer fits the tree (already
    landed, tree diverged) fails CLEAN — no partial application, the working
    tree is untouched. Success returns ``{"ok": True, ...}``; the caller then
    runs the normal solidify path (gate + anchor judge the landing as usual).
    """
    import subprocess
    import tempfile

    replay = entry.get("replay") or {}
    if replay.get("kind") != "unified_diff" or not replay.get("diff"):
        return {"ok": False, "error": "variant carries no replayable diff"}
    diff = str(replay["diff"])
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False, encoding="utf-8") as fh:
        fh.write(diff)
        diff_path = fh.name
    try:
        check = subprocess.run(
            ["git", "apply", "--check", diff_path],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if check.returncode != 0:
            return {
                "ok": False,
                "error": f"diff no longer applies: {(check.stderr or '')[:200]}",
                "hint": "tree diverged or edit already landed — treat as stale",
            }
        applied = subprocess.run(
            ["git", "apply", diff_path],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if applied.returncode != 0:
            return {
                "ok": False,
                "error": f"apply failed after check passed: {(applied.stderr or '')[:200]}",
            }
    finally:
        Path(diff_path).unlink(missing_ok=True)
    return {
        "ok": True,
        "variant_id": entry.get("variant_id"),
        "applied_diff_chars": len(diff),
    }


__all__ = [
    "ENVIRONMENTAL_MARKERS",
    "apply_variant",
    "classify_rejection",
    "load_variants",
    "re_dispatchable_variants",
    "record_variant",
    "variant_entry",
]
