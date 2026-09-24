"""Frozen bench-pack gate — the charter's external-fitness acceptance layer.

Charter (演进方案.md, 2026-09-24, 外部适应度 step 2): one ``evolver.bench``
task pack becomes an additional solidify acceptance condition — a pack-score
drop rejects; flat or up passes (given cascade and anchors). The scoring
rules live OUT-OF-REPO on the anchor side (``$EVOLVER_HOME/anchor/bench/``),
read-only in-cycle: an in-cycle mutation cannot weaken its own gate.

Freeze is a deterministic setup action (``evolver bench freeze``): it writes
the built-in pack to the canonical path and is idempotent without
``--force`` (re-freezing is a human decision — the instrument forbids it).
The gate grades the pack's ``val`` split sandboxes as they stand; the HOST
completes the val tasks each cycle (bridge-mode contract: the prompt is the
interface — the engine never runs an agent).

Baseline semantics mirror the T0 acceptance baseline: the persisted score of
the last ACCEPTED state (not r_best — flat is a pass, only a drop rejects).
First armed run with no baseline establishes it and accepts. Unmeasured
candidates (no graded val task — sandboxes absent) claim nothing: pass
without a baseline update. The baseline binds the pack digest; a re-frozen
pack voids it (``rekeyed`` — recorded, not hidden).

No new ``EVOLVER_*`` knobs — the gate is armed by the frozen pack's
existence, nothing else.

No Node.js equivalent; evolver.py self-research addition (charter 2026-09-24).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Final

from evolver.bench.builtin_pack import write_pack
from evolver.bench.scoring import grade
from evolver.bench.tasks import validate_tasks
from evolver.gep.anchor import anchor_dir
from evolver.gep.paths import get_gep_assets_dir

#: Anchor-side gate directory (outside every workspace — 环内只读).
CHARTER_PACK_SUBDIR: Final = "bench"
CHARTER_PACK_FILENAME: Final = "charter-pack.tasks.json"
#: Baseline record format marker.
BASELINE_FORMAT: Final = "evolver.bench_pack_baseline.v0"
#: The gate only gates on the val split (S26.4: gate ONLY on val).
GATE_SPLIT: Final = "val"


def frozen_pack_path() -> Path:
    """Canonical anchor-side frozen pack path."""
    return anchor_dir() / CHARTER_PACK_SUBDIR / CHARTER_PACK_FILENAME


def sandbox_root(pack_path: Path) -> Path:
    """Sandboxes live next to the pack (same layout as ``bench run``)."""
    return pack_path.resolve().parent / "sandboxes"


def pack_digest(path: Path) -> str:
    """Short SHA-256 of the frozen pack bytes — binds the baseline to the
    exact scoring rules it was established under."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def freeze_charter_pack(*, force: bool = False) -> dict[str, Any]:
    """Write the built-in pack to the frozen gate path. Idempotent without
    *force*: an existing frozen pack is never silently replaced (a weaker
    pack must not be freezable from inside a cycle)."""
    path = frozen_pack_path()
    if path.exists() and not force:
        return {
            "path": str(path),
            "frozen": False,
            "digest": pack_digest(path),
            "tasks": len(json.loads(path.read_text(encoding="utf-8")).get("tasks") or []),
        }
    written = write_pack(path)
    tasks = json.loads(written.read_text(encoding="utf-8")).get("tasks") or []
    return {
        "path": str(written),
        "frozen": True,
        "digest": pack_digest(written),
        "tasks": len(tasks),
    }


def load_frozen_pack() -> tuple[list[dict[str, Any]], str] | None:
    """(tasks, digest) of the frozen pack, or ``None`` when absent/invalid —
    an unusable pack degrades the gate to inactive, never crashes solidify."""
    path = frozen_pack_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        tasks = raw.get("tasks") if isinstance(raw, dict) else raw
        if not isinstance(tasks, list) or validate_tasks(tasks):
            return None
        return tasks, pack_digest(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Baseline: the last-accepted pack score (drop detector, not r_best)
# ---------------------------------------------------------------------------


def baseline_path() -> Path:
    return get_gep_assets_dir() / "acceptance" / "bench_pack_baseline.json"


def load_baseline() -> dict[str, Any] | None:
    """Persisted last-accepted record, or ``None`` when absent/corrupt."""
    path = baseline_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("score"), (int, float)):
        return None
    return payload


def save_baseline(score: float, digest: str) -> None:
    path = baseline_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": BASELINE_FORMAT,
        "score": score,
        "pack_digest": digest,
        "split": GATE_SPLIT,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Grading + verdict
# ---------------------------------------------------------------------------


def grade_split(
    tasks: list[dict[str, Any]],
    root: Path,
    *,
    split: str = GATE_SPLIT,
) -> tuple[list[dict[str, Any]], float | None]:
    """Grade one split's sandboxes as they stand. Quiet core of
    ``runner.run_pack`` — no prints, no ledger write (the gate is a decision,
    not a measurement claim). Missing sandboxes are ``pending`` and excluded;
    an all-pending split scores ``None`` (unmeasured)."""
    per_task: list[dict[str, Any]] = []
    earned = 0.0
    counted = 0
    for task in tasks:
        if task.get("split") != split:
            continue
        tid = str(task["id"])
        sb = root / tid
        if not sb.exists():
            per_task.append({"id": tid, "status": "pending"})
            continue
        task_score = grade(task, sb)
        earned += task_score
        counted += 1
        per_task.append({"id": tid, "status": "graded", "score": task_score})
    return per_task, (round(earned / counted, 4) if counted else None)


def gate_verdict() -> dict[str, Any] | None:
    """Grade the frozen pack's val split and decide against the baseline.

    Verdicts: ``established`` (first armed run), ``rekeyed`` (pack digest
    changed — old baseline void), ``pass`` (flat or up; baseline advances),
    ``reject`` (score dropped; baseline untouched), ``unmeasured`` (nothing
    graded; baseline untouched). ``None`` → gate inactive (pack absent).
    """
    loaded = load_frozen_pack()
    if loaded is None:
        return None
    tasks, digest = loaded
    pack_path = frozen_pack_path()
    per_task, score = grade_split(tasks, sandbox_root(pack_path))

    baseline = load_baseline()
    rekeyed = baseline is not None and baseline.get("pack_digest") != digest
    if rekeyed:
        baseline = None  # the rules changed; the old bar is void

    if score is None:
        verdict = "unmeasured"
    elif baseline is None:
        save_baseline(score, digest)
        verdict = "rekeyed" if rekeyed else "established"
    elif score < float(baseline["score"]):
        verdict = "reject"
    else:
        save_baseline(score, digest)
        verdict = "pass"

    return {
        "armed": True,
        "pack": str(pack_path),
        "digest": digest,
        "split": GATE_SPLIT,
        "score": score,
        "baseline": (float(baseline["score"]) if baseline is not None else None),
        "verdict": verdict,
        "per_task": per_task,
    }


def gate_snapshot() -> dict[str, Any]:
    """Cheap state for ``swarm_status`` / the instrument — no grading."""
    loaded = load_frozen_pack()
    if loaded is None:
        return {"armed": False, "pack": str(frozen_pack_path())}
    tasks, digest = loaded
    val_tasks = sum(1 for t in tasks if t.get("split") == GATE_SPLIT)
    baseline = load_baseline()
    return {
        "armed": True,
        "pack": str(frozen_pack_path()),
        "digest": digest,
        "val_tasks": val_tasks,
        "baseline": (float(baseline["score"]) if baseline is not None else None),
        "baseline_digest": (str(baseline.get("pack_digest")) if baseline else None),
    }


__all__ = [
    "BASELINE_FORMAT",
    "CHARTER_PACK_FILENAME",
    "CHARTER_PACK_SUBDIR",
    "GATE_SPLIT",
    "baseline_path",
    "freeze_charter_pack",
    "frozen_pack_path",
    "gate_snapshot",
    "gate_verdict",
    "grade_split",
    "load_baseline",
    "load_frozen_pack",
    "pack_digest",
    "sandbox_root",
]
