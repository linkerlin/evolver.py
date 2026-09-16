"""Out-of-tree anchor evaluation: frozen contracts guarding the verifier.

RSI roadmap P0-1 (RSI演进对照.md), after arXiv:2609.11873 §3.6.2 (RQGM
discipline): the acceptance gate and its guardians (cascade tests, rollback,
env normalization) are IN-TREE mutable code — a mutation that weakens the
gate and its tests together would be accepted by the weakened gate. The
self-preferencing loop is structurally open; until now only human review
stood in it.

The anchor closes it out-of-tree: a human-managed, version-frozen suite of
self-contained behavior probes under ``$EVOLVER_HOME/anchor/`` (never inside
any workspace the engine may mutate). Probes exercise engine behavior
directly — they import evolver against the CURRENT working tree, so a
mutation that regresses a guarded invariant fails the anchor even when the
mutation also rewrote the in-repo tests that used to catch it.

Discipline:
- The evolution loop (solidify) only ever READS the anchor dir.
- Only the human CLI (``evolver anchor init``) writes it; replacing the set
  means a new epoch recorded in ``epoch.json``.
- Missing/empty anchor dir degrades to skip-with-note (opt-in protection,
  loud in logs) — never blocks machines that have not adopted anchors.

No Node.js equivalent; evolver.py self-research addition (RSI P0-1).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from evolver.config import ANCHOR_PROBE_TIMEOUT_S, ANCHOR_TRIGGER_SURFACES
from evolver.gep.git_ops import normalize_rel_path
from evolver.gep.validation_env import validation_env


def anchor_dir() -> Path:
    """Anchor suite home: ``$EVOLVER_HOME/anchor`` (outside every workspace)."""
    from evolver.gep.paths import get_evolver_home

    return get_evolver_home() / "anchor"


def load_epoch() -> dict[str, Any] | None:
    """Read ``epoch.json``; ``None`` when the anchor suite is not installed."""
    path = anchor_dir() / "epoch.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def list_anchor_cases() -> list[dict[str, Any]]:
    """Enumerate installed anchor cases (each a dir with case.json + probe.py)."""
    root = anchor_dir()
    if not root.is_dir():
        return []
    cases: list[dict[str, Any]] = []
    for case_dir in sorted(root.iterdir()):
        meta = case_dir / "case.json"
        probe = case_dir / "probe.py"
        if not meta.is_file() or not probe.is_file():
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("id"):
            data["_dir"] = str(case_dir)
            cases.append(data)
    return cases


def touches_verifier_surface(changed_files: list[str]) -> list[str]:
    """Changed paths whose mutation may weaken the verification machinery.

    Matched against :data:`ANCHOR_TRIGGER_SURFACES` prefixes; runtime state
    is filtered by the caller.
    """
    matched: list[str] = []
    for raw in changed_files:
        rel = normalize_rel_path(str(raw))
        if any(rel == p or rel.startswith(p) for p in ANCHOR_TRIGGER_SURFACES):
            matched.append(rel)
    return matched


def run_anchor_suite(*, only: set[str] | None = None) -> dict[str, Any]:
    """Run installed probes; each is an isolated subprocess contract.

    Returns ``{"ok": bool, "epoch": int | None, "results": [...], ...}``.
    ``ok`` is True on skip (missing suite) — anchors are opt-in protection;
    the skip is loud (``note``) so logs and events show the gap.
    """
    started = time.time() * 1000.0
    epoch = load_epoch()
    cases = list_anchor_cases()
    if only is not None:
        cases = [c for c in cases if str(c.get("id")) in only]
    results: list[dict[str, Any]] = []
    if epoch is None or not cases:
        return {
            "ok": True,
            "skipped": "anchor_suite_not_installed" if epoch is None else "no_cases",
            "epoch": int(epoch["epoch"]) if epoch and epoch.get("epoch") else None,
            "results": [],
            "started_at": started,
            "finished_at": time.time() * 1000.0,
        }
    env = dict(validation_env())
    env["EVOLVER_ANCHOR_PROBE"] = "1"
    for case in cases:
        probe = Path(str(case["_dir"])) / "probe.py"
        result: dict[str, Any] = {
            "id": str(case.get("id")),
            "title": str(case.get("title") or ""),
            "ok": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
        }
        t0 = time.time()
        try:
            proc = subprocess.run(
                [sys.executable, str(probe)],
                cwd=str(Path(str(case["_dir"]))),
                capture_output=True,
                text=True,
                timeout=ANCHOR_PROBE_TIMEOUT_S,
                check=False,
                shell=False,
                env=env,
            )
            result["exit_code"] = proc.returncode
            result["ok"] = proc.returncode == 0
            result["stdout"] = (proc.stdout or "")[-2000:]
            result["stderr"] = (proc.stderr or "")[-2000:]
        except subprocess.TimeoutExpired:
            result["stderr"] = f"probe timed out after {ANCHOR_PROBE_TIMEOUT_S}s"
        except OSError as exc:
            result["stderr"] = str(exc)[:500]
        result["duration_ms"] = round((time.time() - t0) * 1000.0)
        results.append(result)
    return {
        "ok": all(r["ok"] for r in results),
        "epoch": int(epoch.get("epoch") or 0),
        "results": results,
        "started_at": started,
        "finished_at": time.time() * 1000.0,
    }


def install_anchor_suite(target: Path | None = None, *, epoch: int = 1) -> dict[str, Any]:
    """Human-only entry (CLI ``evolver anchor init``): freeze the packaged
    seed suite into the anchor dir. Refuses to overwrite an installed epoch
    unless ``epoch`` is strictly greater (replacement = new epoch)."""
    import shutil

    from evolver.gep.paths import get_evolver_home

    root = target or (get_evolver_home() / "anchor")
    existing = load_epoch() if target is None else _read_epoch_at(root)
    if existing and int(existing.get("epoch") or 0) >= epoch:
        return {
            "ok": False,
            "error": "epoch_not_newer",
            "installed_epoch": existing.get("epoch"),
            "hint": "replacement requires a strictly greater --epoch",
        }
    seed = Path(__file__).resolve().parent.parent / "assets" / "anchor"
    if not seed.is_dir():
        return {"ok": False, "error": "seed_missing", "path": str(seed)}
    root.mkdir(parents=True, exist_ok=True)
    for case_dir in sorted(seed.iterdir()):
        if not case_dir.is_dir():
            continue
        dest = root / case_dir.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(case_dir, dest)
    epoch_doc = {
        "epoch": epoch,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "frozen verifier contracts (RSI P0-1); engine reads, never writes",
        "cases": sorted(p.name for p in seed.iterdir() if p.is_dir()),
    }
    (root / "epoch.json").write_text(json.dumps(epoch_doc, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "epoch": epoch, "cases": epoch_doc["cases"], "path": str(root)}


def _read_epoch_at(root: Path) -> dict[str, Any] | None:
    path = root / "epoch.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


__all__ = [
    "anchor_dir",
    "install_anchor_suite",
    "list_anchor_cases",
    "load_epoch",
    "run_anchor_suite",
    "touches_verifier_surface",
]
