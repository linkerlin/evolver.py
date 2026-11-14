"""AST reverse-dependency graph & <3s lightning validation planner (P1-3).

Builds and incrementally caches a repository-wide Python import graph using
only stdlib ``ast`` (keyed by ``(mtime_ns, size)`` in
``<workspace_state_dir>/import_graph.json``), then routes mutations through a
three-tier verification funnel:

- **L0 (Lightning, < 3s target)**: ``ruff check <changed_py_files>`` +
  ``pytest -m "not slow" -q --maxfail=3 <impacted_tests>`` computed via
  transitive reverse-dependency closure (+ stem-matched test files).
- **L1 (Guardian check)**: isolated ``mypy`` + broader sibling-test check in an
  eval worktree; demotes regressed genes to ``under_review`` in
  :mod:`evolver.gep.gene_lifecycle`.
- **L2 (Full Cascade + Anchor)**: automatic escalation whenever a change
  touches ``ANCHOR_TRIGGER_SURFACES``, ``pyproject.toml``, or any ``conftest.py``.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from evolver.gep.anchor import touches_verifier_surface
from evolver.gep.paths import get_workspace_state_dir

logger = logging.getLogger(__name__)

GRAPH_SCHEMA_VERSION: Final = 1

_EXCLUDED_DIRS: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        "node_modules",
        "build",
        "dist",
        ".eggs",
        ".evolver",
        ".evolver_settings",
        ".evomap",
        "memory",
        "logs",
    }
)

_GLOBAL_ESCALATION_FILENAMES: Final[frozenset[str]] = frozenset(
    {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "conftest.py",
    }
)


@dataclass(frozen=True)
class ValidationPlan:
    """Resolved validation plan for a pending workspace mutation."""

    tier: str  # "L0" | "L2"
    reason: str
    changed_files: list[str] = field(default_factory=list)
    changed_py_files: list[str] = field(default_factory=list)
    impacted_tests: list[str] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "reason": self.reason,
            "changed_files": list(self.changed_files),
            "changed_py_files": list(self.changed_py_files),
            "impacted_tests": list(self.impacted_tests),
            "commands": [dict(c) for c in self.commands],
        }


def _norm_rel(path_str: str) -> str:
    return path_str.replace("\\", "/").strip().lstrip("./")


def _is_test_file(rel_posix: str) -> bool:
    if not rel_posix.endswith(".py"):
        return False
    name = Path(rel_posix).name
    return name.startswith("test_") or name.endswith("_test.py")


def _module_names_for_rel(rel_posix: str) -> list[str]:
    """Return candidate dotted module names for *rel_posix*."""
    if not rel_posix.endswith(".py"):
        return []
    parts = [p for p in rel_posix[:-3].split("/") if p]
    if not parts:
        return []

    candidates: list[str] = []

    def _add_from_parts(tokens: list[str]) -> None:
        if not tokens:
            return
        mod = ".".join(tokens[:-1]) if tokens[-1] == "__init__" else ".".join(tokens)
        if mod and mod not in candidates:
            candidates.append(mod)

    if parts[0] == "src" and len(parts) > 1:
        _add_from_parts(parts[1:])
    _add_from_parts(parts)
    return candidates


def _package_prefix_for_rel(rel_posix: str) -> list[str]:
    """Return package tokens for resolving relative imports inside *rel_posix*."""
    parts = [p for p in rel_posix[:-3].split("/") if p]
    if parts and parts[0] == "src" and len(parts) > 1:
        parts = parts[1:]
    if not parts:
        return []
    if parts[-1] == "__init__":
        return parts[:-1]
    return parts[:-1]


def _extract_file_imports(source: str, rel_posix: str) -> list[str]:
    """Parse *source* with stdlib ``ast`` and return candidate imported module names."""
    try:
        tree = ast.parse(source, filename=rel_posix)
    except SyntaxError:
        return []

    pkg_tokens = _package_prefix_for_rel(rel_posix)
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name.strip()
                if name:
                    found.add(name)
        elif isinstance(node, ast.ImportFrom):
            base_tokens: list[str] = []
            if node.level and node.level > 0:
                up = node.level - 1
                if up <= len(pkg_tokens):
                    base_tokens = list(pkg_tokens[: len(pkg_tokens) - up])
            if node.module:
                mod_tokens = [t for t in node.module.split(".") if t]
                full_mod = ".".join([*base_tokens, *mod_tokens])
            else:
                full_mod = ".".join(base_tokens)
            if full_mod:
                found.add(full_mod)
            for alias in node.names:
                if alias.name and alias.name != "*":
                    sub = f"{full_mod}.{alias.name}" if full_mod else alias.name
                    found.add(sub)

    return sorted(found)


def graph_cache_path(repo_root: Path) -> Path:
    """Externalized cache file location under ``~/.evolver/workspaces/<id>/``."""
    return get_workspace_state_dir(repo_root) / "import_graph.json"


def _scan_python_files(repo_root: Path) -> list[tuple[str, Path, int, int]]:
    """Return ``(rel_posix, abs_path, mtime_ns, size)`` for every project ``.py`` file."""
    discovered: list[tuple[str, Path, int, int]] = []
    for root_str, dirs, files in os.walk(repo_root):
        dirs[:] = [
            d
            for d in dirs
            if d not in _EXCLUDED_DIRS and not d.endswith(".egg-info") and not d.startswith(".git")
        ]
        root_path = Path(root_str)
        for fname in files:
            if not fname.endswith(".py"):
                continue
            abs_p = root_path / fname
            try:
                st = abs_p.stat()
            except OSError:
                continue
            try:
                rel = abs_p.relative_to(repo_root).as_posix()
            except ValueError:
                continue
            discovered.append((rel, abs_p, st.st_mtime_ns, st.st_size))
    discovered.sort(key=lambda item: item[0])
    return discovered


def build_or_load_import_graph(
    repo_root: Path,
    *,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """Incrementally build or update the AST import graph for *repo_root*.

    Returns a dictionary containing:
    - ``files``: ``{rel_posix: {"mtime_ns": int, "size": int, "imports": [...], "modules": [...]}}``
    - ``reverse_deps``: ``{target_rel_posix: [importer_rel_posix, ...]}``
    - ``stats``: ``{"total_files": int, "parsed_files": int, "cached_files": int}``
    """
    repo_root = repo_root.resolve()
    cpath = cache_path or graph_cache_path(repo_root)

    cached_files: dict[str, dict[str, Any]] = {}
    if cpath.is_file():
        try:
            raw = json.loads(cpath.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and raw.get("version") == GRAPH_SCHEMA_VERSION:
                raw_files = raw.get("files")
                if isinstance(raw_files, dict):
                    cached_files = raw_files
        except (OSError, json.JSONDecodeError):
            cached_files = {}

    scanned = _scan_python_files(repo_root)
    next_files: dict[str, dict[str, Any]] = {}
    parsed_count = 0
    reused_count = 0
    dirty = len(scanned) != len(cached_files)

    for rel, abs_p, mtime_ns, size in scanned:
        prev = cached_files.get(rel)
        if (
            isinstance(prev, dict)
            and prev.get("mtime_ns") == mtime_ns
            and prev.get("size") == size
            and isinstance(prev.get("imports"), list)
            and isinstance(prev.get("modules"), list)
        ):
            next_files[rel] = prev
            reused_count += 1
            continue

        try:
            src = abs_p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            src = ""
        imports = _extract_file_imports(src, rel)
        modules = _module_names_for_rel(rel)
        next_files[rel] = {
            "mtime_ns": mtime_ns,
            "size": size,
            "imports": imports,
            "modules": modules,
        }
        parsed_count += 1
        dirty = True

    if dirty or not cpath.is_file():
        try:
            cpath.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": GRAPH_SCHEMA_VERSION,
                "repo_root": str(repo_root),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "files": next_files,
            }
            tmp = cpath.with_name(f"{cpath.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            tmp.replace(cpath)
        except OSError:
            logger.debug("[import_graph] cache write skipped for %s", cpath, exc_info=True)

    module_to_files: dict[str, set[str]] = {}
    for rel, meta in next_files.items():
        for mod in meta.get("modules", []):
            module_to_files.setdefault(mod, set()).add(rel)

    reverse_sets: dict[str, set[str]] = {rel: set() for rel in next_files}
    for importer_rel, meta in next_files.items():
        for imp in meta.get("imports", []):
            # Match exact module or any parent package prefix that maps to a project file.
            tokens = imp.split(".")
            for i in range(len(tokens), 0, -1):
                prefix = ".".join(tokens[:i])
                targets = module_to_files.get(prefix)
                if targets:
                    for target_rel in targets:
                        if target_rel != importer_rel:
                            reverse_sets.setdefault(target_rel, set()).add(importer_rel)
                    break

    reverse_deps = {k: sorted(v) for k, v in reverse_sets.items() if v}
    return {
        "files": next_files,
        "reverse_deps": reverse_deps,
        "stats": {
            "total_files": len(next_files),
            "parsed_files": parsed_count,
            "cached_files": reused_count,
        },
    }


def find_impacted_tests(
    repo_root: Path,
    changed_files: Sequence[str],
    *,
    graph: dict[str, Any] | None = None,
) -> list[str]:
    """Compute transitive reverse-dependency test closure for *changed_files*."""
    repo_root = repo_root.resolve()
    g = graph if graph is not None else build_or_load_import_graph(repo_root)
    all_files: dict[str, Any] = g.get("files") or {}
    reverse_deps: dict[str, list[str]] = g.get("reverse_deps") or {}

    norm_changed = [_norm_rel(f) for f in changed_files if f and _norm_rel(f)]
    visited: set[str] = set()
    queue: deque[str] = deque()

    for rel in norm_changed:
        if rel in all_files and rel not in visited:
            visited.add(rel)
            queue.append(rel)

    while queue:
        curr = queue.popleft()
        for dep in reverse_deps.get(curr, ()):
            if dep not in visited:
                visited.add(dep)
                queue.append(dep)

    impacted: set[str] = {
        rel for rel in visited if _is_test_file(rel) and (repo_root / rel).is_file()
    }

    # Direct test edits (including brand-new untracked test files not yet cached)
    for rel in norm_changed:
        if _is_test_file(rel) and (repo_root / rel).is_file():
            impacted.add(rel)

    # Convention fallback: match test_<stem>.py / <stem>_test.py for changed Python modules
    changed_stems = {
        Path(rel).stem
        for rel in norm_changed
        if rel.endswith(".py") and not _is_test_file(rel) and Path(rel).stem != "__init__"
    }
    if changed_stems:
        for rel in all_files:
            if not _is_test_file(rel):
                continue
            name = Path(rel).stem
            bare = name.removeprefix("test_").removesuffix("_test")
            if bare in changed_stems and (repo_root / rel).is_file():
                impacted.add(rel)

    return sorted(impacted)


def _resolve_tool_argv(tool: str) -> list[str] | None:
    """Resolve *tool* on PATH or beside ``sys.executable``."""
    found = shutil.which(tool)
    if found:
        return [found]
    bin_dir = Path(sys.executable).parent
    local = bin_dir / tool
    if local.is_file():
        return [str(local)]
    via_bin = shutil.which(tool, path=str(bin_dir))
    if via_bin:
        return [via_bin]
    if tool in ("pytest", "mypy", "ruff"):
        # Verify module availability under sys.executable for hermetically isolated venvs
        return [sys.executable, "-m", tool] if tool != "ruff" else None
    return None


def requires_l2_escalation(changed_files: Sequence[str]) -> tuple[bool, str]:
    """Return ``(True, reason)`` when *changed_files* touch high-risk or global surfaces."""
    norm = [_norm_rel(f) for f in changed_files if f and _norm_rel(f)]
    if not norm:
        return False, ""

    verifier_hits = touches_verifier_surface(norm)
    if verifier_hits:
        return True, f"verifier_surface:{verifier_hits[0]}"

    for rel in norm:
        fname = Path(rel).name
        if fname in _GLOBAL_ESCALATION_FILENAMES:
            return True, f"global_config:{rel}"

    return False, ""


def select_validation_plan(
    repo_root: Path,
    changed_files: Sequence[str],
) -> ValidationPlan:
    """Select ``L0`` lightning validation or ``L2`` full cascade escalation."""
    repo_root = repo_root.resolve()
    norm_changed = sorted({_norm_rel(f) for f in changed_files if f and _norm_rel(f)})

    escalate, esc_reason = requires_l2_escalation(norm_changed)
    if escalate:
        return ValidationPlan(
            tier="L2",
            reason=esc_reason,
            changed_files=norm_changed,
            changed_py_files=[
                f for f in norm_changed if f.endswith(".py") and (repo_root / f).is_file()
            ],
        )

    changed_py = [f for f in norm_changed if f.endswith(".py") and (repo_root / f).is_file()]
    if not changed_py:
        return ValidationPlan(
            tier="L0",
            reason="no_python_changes",
            changed_files=norm_changed,
            changed_py_files=[],
            impacted_tests=[],
            commands=[],
        )

    graph = build_or_load_import_graph(repo_root)
    impacted = find_impacted_tests(repo_root, norm_changed, graph=graph)

    commands: list[dict[str, Any]] = []
    ruff_bin = _resolve_tool_argv("ruff")
    if ruff_bin is not None:
        commands.append(
            {
                "command": [*ruff_bin, "check", *changed_py],
                "timeout_ms": 15_000,
            }
        )

    if impacted:
        pytest_bin = _resolve_tool_argv("pytest")
        if pytest_bin is not None:
            commands.append(
                {
                    "command": [
                        *pytest_bin,
                        "-m",
                        "not slow",
                        "-q",
                        "--maxfail=3",
                        *impacted,
                    ],
                    "timeout_ms": 60_000,
                }
            )

    return ValidationPlan(
        tier="L0",
        reason="ast_reverse_dependency",
        changed_files=norm_changed,
        changed_py_files=changed_py,
        impacted_tests=impacted,
        commands=commands,
    )


def demote_gene_on_guardian_failure(
    gene_id: str,
    *,
    reason: str = "l1_guardian_regression",
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Demote *gene_id* to ``under_review`` in ``gene_lifecycle`` after an L1 failure."""
    gid = str(gene_id or "").strip()
    if not gid:
        return {"ok": False, "reason": "empty_gene_id"}

    from evolver.gep.asset_store import append_jsonl, atomic_write_json, with_file_lock
    from evolver.gep.gene_lifecycle import (
        GeneLifecycleRecord,
        GeneLifecycleStoreError,
        lifecycle_audit_path,
        lifecycle_path,
        load_lifecycle,
    )

    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with with_file_lock(target_path=lifecycle_path()):
        try:
            states = load_lifecycle(strict=True)
        except GeneLifecycleStoreError as exc:
            return {"ok": False, "error": "lifecycle_store_corrupt", "detail": str(exc)}

        prev = states.get(gid)
        prev_status = prev.status if prev is not None else "active"
        if prev_status == "retired":
            return {"ok": True, "demoted": False, "status": "retired"}

        ev = dict(evidence or {})
        states[gid] = GeneLifecycleRecord(
            gene_id=gid,
            status="under_review",
            since=ts,
            reason=reason,
            evidence=ev,
            reinstated_count=prev.reinstated_count if prev else 0,
        )
        payload = {
            "version": 1,
            "updated_at": ts,
            "genes": {k: v.model_dump() for k, v in sorted(states.items())},
        }
        atomic_write_json(lifecycle_path(), payload)
        append_jsonl(
            lifecycle_audit_path(),
            {
                "ts": ts,
                "actor": "l1_guardian",
                "gene_id": gid,
                "from_status": prev_status,
                "to_status": "under_review",
                "reason": reason,
                "evidence": ev,
            },
        )
        return {"ok": True, "demoted": True, "gene_id": gid, "status": "under_review"}


def run_l1_guardian_check(
    repo_root: Path,
    changed_files: Sequence[str],
    *,
    gene_id: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    """Run L1 incremental ``mypy`` + sibling tests in an isolated eval worktree.

    If L1 fails after an L0 promotion, demotes *gene_id* to ``under_review``
    and records a structured audit trail.
    """
    from evolver.gep.eval_worktree import isolated_eval_cwd
    from evolver.gep.validation_env import validation_env

    repo_root = repo_root.resolve()
    norm_changed = [_norm_rel(f) for f in changed_files if f and _norm_rel(f)]
    src_py = [
        f
        for f in norm_changed
        if f.endswith(".py") and not _is_test_file(f) and (repo_root / f).is_file()
    ]
    if not src_py:
        return {"ok": True, "skipped": True, "reason": "no_src_py_files"}

    mypy_bin = _resolve_tool_argv("mypy")
    if mypy_bin is None:
        return {"ok": True, "skipped": True, "reason": "mypy_unavailable"}

    t0 = time.monotonic()
    with isolated_eval_cwd(repo_root) as (eval_cwd, _meta):
        try:
            proc = subprocess.run(
                [*mypy_bin, *src_py],
                cwd=eval_cwd,
                capture_output=True,
                text=True,
                timeout=120.0,
                shell=False,
                check=False,
                env=validation_env(),
            )
            ok = proc.returncode == 0
            out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        except Exception as exc:
            ok = False
            out = str(exc)

    duration_ms = round((time.monotonic() - t0) * 1000.0)
    demotion: dict[str, Any] | None = None
    if not ok and gene_id:
        demotion = demote_gene_on_guardian_failure(
            gene_id,
            reason="l1_guardian_mypy_failed",
            evidence={
                "run_id": run_id,
                "changed_files": src_py[:20],
                "output_tail": out[-500:],
                "duration_ms": duration_ms,
            },
        )
    return {
        "ok": ok,
        "tier": "L1",
        "duration_ms": duration_ms,
        "checked_files": src_py,
        "output": out[-1000:],
        "demotion": demotion,
    }


def spawn_l1_guardian_background(
    repo_root: Path,
    changed_files: Sequence[str],
    *,
    gene_id: str = "",
    run_id: str = "",
) -> bool:
    """Spawn L1 guardian check on a daemon thread outside pytest runs."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    files_copy = list(changed_files)
    root_copy = repo_root.resolve()

    def _worker() -> None:
        try:
            run_l1_guardian_check(
                root_copy,
                files_copy,
                gene_id=gene_id,
                run_id=run_id,
            )
        except Exception:
            logger.debug("[import_graph] L1 guardian background check failed", exc_info=True)

    t = threading.Thread(target=_worker, name=f"evolver-l1-{run_id[-8:]}", daemon=True)
    t.start()
    return True


__all__ = [
    "GRAPH_SCHEMA_VERSION",
    "ValidationPlan",
    "build_or_load_import_graph",
    "demote_gene_on_guardian_failure",
    "find_impacted_tests",
    "graph_cache_path",
    "requires_l2_escalation",
    "run_l1_guardian_check",
    "select_validation_plan",
    "spawn_l1_guardian_background",
]
