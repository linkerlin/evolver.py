"""Cycle-boundary in-band blackbox flight recorder (算子即基因 P1-2).

Eliminates the ``relay=0%`` external HTTP proxy blind spot by capturing 100%
engine-verified process telemetry directly across the ``evolve_begin`` <->
``evolve_settle`` boundary:
- pre/post ``HEAD`` & dirty file snapshot;
- pre/post Python AST symbol digest & structural ``ast_delta`` (added,
  modified, and removed functions/classes);
- bounded ``run_lens`` diagnostic call stack & wall-clock timing;
- validation tier, stage counts, and pass rate.

Stored exclusively under externalized runtime state (``<EVOLUTION_DIR>``):
- ``active_blackbox.json`` while an ``ACTIVE_RUN`` is open;
- ``blackbox_telemetry.jsonl`` append-only settled round ledger.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from evolver.gep.asset_store import append_jsonl, atomic_write_json
from evolver.gep.git_ops import (
    capture_diff_snapshot,
    git_head,
    git_list_changed_files,
    git_list_untracked_files,
)
from evolver.gep.paths import get_evolution_dir

ACTIVE_BLACKBOX_FILENAME: Final = "active_blackbox.json"
BLACKBOX_TELEMETRY_FILENAME: Final = "blackbox_telemetry.jsonl"
BLACKBOX_SCHEMA_VERSION: Final = 1
_MAX_LENS_CALLS: Final = 32
_MAX_AST_FILES: Final = 40


def active_blackbox_path(evolution_dir: Path | None = None) -> Path:
    return (evolution_dir or get_evolution_dir()) / ACTIVE_BLACKBOX_FILENAME


def blackbox_telemetry_path(evolution_dir: Path | None = None) -> Path:
    return (evolution_dir or get_evolution_dir()) / BLACKBOX_TELEMETRY_FILENAME


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _dirty_files(cwd: Path) -> list[str]:
    seen: list[str] = []
    for raw in git_list_changed_files(cwd) + git_list_untracked_files(cwd):
        norm = raw.replace("\\", "/").strip()
        if norm and not norm.startswith((".evolver/", ".evomap/", "memory/")) and norm not in seen:
            seen.append(norm)
    return seen[:100]


def _ast_symbol_map(py_path: Path) -> dict[str, str]:
    """Return ``{qualname: sha256_prefix}`` for top-level and class methods in *py_path*."""
    try:
        src = py_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
    except (OSError, SyntaxError):
        return {}

    digests: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            dumped = ast.dump(node, include_attributes=False)
            digests[f"fn:{node.name}"] = hashlib.sha256(dumped.encode("utf-8")).hexdigest()[:12]
        elif isinstance(node, ast.ClassDef):
            dumped = ast.dump(node, include_attributes=False)
            digests[f"cls:{node.name}"] = hashlib.sha256(dumped.encode("utf-8")).hexdigest()[:12]
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef):
                    sub_dump = ast.dump(sub, include_attributes=False)
                    digests[f"method:{node.name}.{sub.name}"] = hashlib.sha256(
                        sub_dump.encode("utf-8")
                    ).hexdigest()[:12]
    return digests


def _snapshot_repo_ast(cwd: Path, rel_files: list[str]) -> dict[str, dict[str, str]]:
    snap: dict[str, dict[str, str]] = {}
    for rel in rel_files[:_MAX_AST_FILES]:
        if not rel.endswith(".py"):
            continue
        p = cwd / rel
        if p.is_file():
            snap[rel] = _ast_symbol_map(p)
    return snap


def _head_file_ast(cwd: Path, rel: str) -> dict[str, str]:
    """Read HEAD version of *rel* via git show when the file was clean at start."""
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "show", f"HEAD:{rel}"],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5.0,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            return {}
        tree = ast.parse(proc.stdout)
    except Exception:
        return {}

    digests: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            dumped = ast.dump(node, include_attributes=False)
            digests[f"fn:{node.name}"] = hashlib.sha256(dumped.encode("utf-8")).hexdigest()[:12]
        elif isinstance(node, ast.ClassDef):
            dumped = ast.dump(node, include_attributes=False)
            digests[f"cls:{node.name}"] = hashlib.sha256(dumped.encode("utf-8")).hexdigest()[:12]
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef):
                    sub_dump = ast.dump(sub, include_attributes=False)
                    digests[f"method:{node.name}.{sub.name}"] = hashlib.sha256(
                        sub_dump.encode("utf-8")
                    ).hexdigest()[:12]
    return digests


def compute_ast_delta(
    cwd: Path,
    before_ast: dict[str, dict[str, str]],
    after_files: list[str],
) -> dict[str, Any]:
    """Compute added/modified/removed AST symbols across touched Python files."""
    added: list[str] = []
    modified: list[str] = []
    removed: list[str] = []

    py_targets = sorted(
        {
            *(f for f in before_ast if f.endswith(".py")),
            *(f for f in after_files[:_MAX_AST_FILES] if f.endswith(".py")),
        }
    )
    for rel in py_targets:
        prev = before_ast.get(rel)
        if prev is None:
            prev = _head_file_ast(cwd, rel)
        cur_path = cwd / rel
        curr = _ast_symbol_map(cur_path) if cur_path.is_file() else {}
        for sym, digest in curr.items():
            label = f"{rel}::{sym}"
            if sym not in prev:
                added.append(label)
            elif prev[sym] != digest:
                modified.append(label)
        for sym in prev:
            if sym not in curr:
                removed.append(f"{rel}::{sym}")

    return {
        "python_files_inspected": len(py_targets),
        "added_count": len(added),
        "modified_count": len(modified),
        "removed_count": len(removed),
        "added": added[:25],
        "modified": modified[:25],
        "removed": removed[:25],
    }


def load_active_blackbox(evolution_dir: Path | None = None) -> dict[str, Any] | None:
    path = active_blackbox_path(evolution_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def begin_blackbox(
    run_id: str,
    cwd: Path,
    *,
    hypothesis: str = "",
    selected_gene_id: str = "",
    evolution_dir: Path | None = None,
) -> dict[str, Any]:
    """Open the cycle-boundary flight recorder at ``evolve_begin``."""
    cwd = cwd.resolve()
    dirty = _dirty_files(cwd)
    state: dict[str, Any] = {
        "schema_version": BLACKBOX_SCHEMA_VERSION,
        "run_id": str(run_id or ""),
        "started_at": _now_iso(),
        "started_epoch_ms": round(time.time() * 1000),
        "head_commit": git_head(cwd) or "",
        "selected_gene_id": str(selected_gene_id or ""),
        "hypothesis_chars": len((hypothesis or "").strip()),
        "initial_dirty_files": dirty,
        "before_ast": _snapshot_repo_ast(cwd, dirty),
        "lens_calls": [],
    }
    path = active_blackbox_path(evolution_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, state)
    return state


def record_lens_call(
    name: str,
    target: str,
    *,
    ok: bool,
    duration_ms: int,
    summary: str = "",
    evolution_dir: Path | None = None,
) -> bool:
    """Append one ``run_lens`` invocation to the active blackbox (if open)."""
    active = load_active_blackbox(evolution_dir)
    if active is None:
        return False
    calls = list(active.get("lens_calls") or [])
    if len(calls) < _MAX_LENS_CALLS:
        calls.append(
            {
                "lens": str(name or ""),
                "target": str(target or ".")[:160],
                "ok": bool(ok),
                "duration_ms": max(0, int(duration_ms)),
                "summary": str(summary or "")[:200],
                "at": _now_iso(),
            }
        )
    active["lens_calls"] = calls
    atomic_write_json(active_blackbox_path(evolution_dir), active)
    return True


def _diff_line_stats(diff_text: str) -> dict[str, int]:
    added = 0
    removed = 0
    for ln in diff_text.splitlines():
        if ln.startswith("+") and not ln.startswith("+++"):
            added += 1
        elif ln.startswith("-") and not ln.startswith("---"):
            removed += 1
    return {"lines_added": added, "lines_removed": removed}


def classify_patch_mechanisms(
    diff_text: str,
    ast_delta: dict[str, Any] | None = None,
) -> list[str]:
    """Classify diff + AST delta into canonical mutation mechanism labels (S-7)."""
    added_lines = [
        ln[1:]
        for ln in (diff_text or "").splitlines()
        if ln.startswith("+") and not ln.startswith("+++")
    ]
    added_blob = "\n".join(added_lines)
    touched_headers = [
        ln[4:].strip() for ln in (diff_text or "").splitlines() if ln.startswith("+++ ")
    ]
    mechs: list[str] = []

    if "try:" in added_blob or "except " in added_blob or "except:" in added_blob:
        mechs.append("try/except wrapping")
    if "if " in added_blob and (
        "return " in added_blob or "is None" in added_blob or "isinstance(" in added_blob
    ):
        mechs.append("guard/early-return")
    if "re.compile" in added_blob or ".replace(" in added_blob or "re.search" in added_blob:
        mechs.append("regex/string patch")
    if any(ln.lstrip().startswith("def ") for ln in added_lines):
        mechs.append("signature/default tweak")
    if any(ln.lstrip().startswith(("import ", "from ")) for ln in added_lines):
        mechs.append("import/routing change")
    if touched_headers and all("test_" in h or "/tests/" in h for h in touched_headers):
        mechs.append("test-only edit")
    if not mechs and (
        added_lines or (isinstance(ast_delta, dict) and ast_delta.get("modified_count"))
    ):
        mechs.append("general logic edit")
    return mechs or ["noop/empty"]


def render_mutation_structure_mirror(
    evolution_dir: Path | None = None,
    *,
    window: int = 5,
    min_unsettled: int = 2,
) -> str:
    """Return a 1-line mirror summarizing recent unsettled draft patterns (S-7)."""
    rows = load_blackbox_telemetry(evolution_dir)
    if not rows:
        return ""
    recent = rows[-max(1, int(window)) :]
    trailing_unsettled: list[dict[str, Any]] = []
    for row in reversed(recent):
        if row.get("outcome_ok") is True or row.get("outcome_label") == "promoted":
            break
        trailing_unsettled.append(row)
    if len(trailing_unsettled) < min_unsettled:
        return ""

    counts: dict[str, int] = {}
    for row in trailing_unsettled:
        mechs = row.get("mechanisms")
        label = (
            str(mechs[0])
            if isinstance(mechs, list) and mechs
            else (
                "ast-edit"
                if isinstance(row.get("ast_delta"), dict) and row["ast_delta"].get("modified_count")
                else "non-ast-edit"
            )
        )
        counts[label] = counts.get(label, 0) + 1

    summary = ", ".join(
        f"{n} {k}" for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    return (
        f"Mirror — Your last {len(trailing_unsettled)} unsettled draft(s) in this workspace: "
        f"{summary} (0 promoted). Your next hypothesis MUST try a structurally distinct mechanism."
    )


def settle_blackbox(
    cwd: Path,
    *,
    run_id: str = "",
    event_id: str = "",
    outcome_ok: bool,
    outcome_label: str = "",
    validation_result: dict[str, Any] | None = None,
    diff_text: str | None = None,
    evolution_dir: Path | None = None,
    clear_active: bool = True,
) -> dict[str, Any]:
    """Close the flight recorder at ``evolve_settle`` and append telemetry."""
    cwd = cwd.resolve()
    active = load_active_blackbox(evolution_dir) or {}
    effective_run_id = str(run_id or active.get("run_id") or "")
    now_ms = round(time.time() * 1000)
    started_ms = active.get("started_epoch_ms")
    wall_time_ms = (
        max(0, now_ms - int(started_ms))
        if isinstance(started_ms, int | float) and started_ms > 0
        else 0
    )

    after_files = _dirty_files(cwd)
    raw_before = active.get("before_ast")
    before_ast: dict[str, dict[str, str]] = raw_before if isinstance(raw_before, dict) else {}
    ast_delta = compute_ast_delta(cwd, before_ast, after_files)
    diff_snap = diff_text if diff_text is not None else capture_diff_snapshot(cwd, max_chars=2000)
    diff_stats = _diff_line_stats(diff_snap)

    raw_lenses = active.get("lens_calls")
    lens_calls: list[dict[str, Any]] = (
        [c for c in raw_lenses if isinstance(c, dict)] if isinstance(raw_lenses, list) else []
    )
    raw_results = validation_result.get("results") if isinstance(validation_result, dict) else None
    results: list[Any] = raw_results if isinstance(raw_results, list) else []
    checks_total = len(results)
    checks_passed = sum(1 for r in results if isinstance(r, dict) and bool(r.get("ok")))
    val_ms = (
        int(validation_result["duration_ms"])
        if isinstance(validation_result, dict)
        and isinstance(validation_result.get("duration_ms"), int | float)
        else None
    )
    val_tier = (
        str(validation_result.get("tier") or "") if isinstance(validation_result, dict) else ""
    )

    summary_entry: dict[str, Any] = {
        "schema_version": BLACKBOX_SCHEMA_VERSION,
        "run_id": effective_run_id,
        "event_id": str(event_id or ""),
        "started_at": active.get("started_at") or _now_iso(),
        "settled_at": _now_iso(),
        "wall_time_ms": wall_time_ms,
        "head_commit": active.get("head_commit") or git_head(cwd) or "",
        "selected_gene_id": active.get("selected_gene_id") or "",
        "outcome_ok": bool(outcome_ok),
        "outcome_label": str(outcome_label or ("promoted" if outcome_ok else "draft_preserved")),
        "touched_files": after_files[:30],
        "diff_stats": diff_stats,
        "ast_delta": ast_delta,
        "mechanisms": classify_patch_mechanisms(diff_snap, ast_delta),
        "lens_calls_count": len(lens_calls),
        "lens_names": sorted({str(c.get("lens") or "") for c in lens_calls if c.get("lens")}),
        "lens_calls": lens_calls[:16],
        "validation": {
            "tier": val_tier or None,
            "duration_ms": val_ms,
            "checks_total": checks_total,
            "checks_passed": checks_passed,
        },
        "source": "engine_blackbox",
    }

    telemetry_file = blackbox_telemetry_path(evolution_dir)
    telemetry_file.parent.mkdir(parents=True, exist_ok=True)
    append_jsonl(telemetry_file, summary_entry)

    if clear_active:
        act_path = active_blackbox_path(evolution_dir)
        if act_path.is_file():
            with contextlib.suppress(OSError):
                act_path.unlink()

    return summary_entry


def load_blackbox_telemetry(evolution_dir: Path | None = None) -> list[dict[str, Any]]:
    """Read settled blackbox entries, oldest first."""
    path = blackbox_telemetry_path(evolution_dir)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def find_blackbox_for_round(
    *,
    run_id: str = "",
    event_id: str = "",
    evolution_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Lookup the most recent settled blackbox entry matching *event_id* or *run_id*."""
    rows = load_blackbox_telemetry(evolution_dir)
    if event_id:
        for row in reversed(rows):
            if str(row.get("event_id") or "") == event_id:
                return row
    if run_id:
        for row in reversed(rows):
            if str(row.get("run_id") or "") == run_id:
                return row
    return None


def clear_active_blackbox(evolution_dir: Path | None = None) -> None:
    path = active_blackbox_path(evolution_dir)
    if path.is_file():
        with contextlib.suppress(OSError):
            path.unlink()


__all__ = [
    "ACTIVE_BLACKBOX_FILENAME",
    "BLACKBOX_SCHEMA_VERSION",
    "BLACKBOX_TELEMETRY_FILENAME",
    "active_blackbox_path",
    "begin_blackbox",
    "blackbox_telemetry_path",
    "classify_patch_mechanisms",
    "clear_active_blackbox",
    "compute_ast_delta",
    "find_blackbox_for_round",
    "load_active_blackbox",
    "load_blackbox_telemetry",
    "record_lens_call",
    "render_mutation_structure_mirror",
    "settle_blackbox",
]
