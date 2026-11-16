"""Built-in deterministic read-only diagnostic lenses (算子即基因 P1-1 / P2-1).

Provides zero-network, side-effect-free Python static and traceback lenses
callable via the ``run_lens`` MCP tool during ``ACTIVE_RUN`` (and from operator
genes carrying executable ``lens`` specifications). All text outputs pass
through ``val_seal.redact`` before returning so sealed validation material can
never leak through diagnostic inspection.
"""

from __future__ import annotations

import ast
import os
import re
import time
from pathlib import Path
from typing import Any, Final

from evolver.config import ANCHOR_TRIGGER_SURFACES
from evolver.gep.import_graph import (
    build_or_load_import_graph,
    find_impacted_tests,
    requires_l2_escalation,
)
from evolver.gep.paths import get_repo_root, get_workspace_root

BUILTIN_LENSES: Final[dict[str, str]] = {
    "list": "List built-in read-only lenses and active operator genes with lens specs.",
    "card": "Render Operator Card(s) with engine-measured stats & notes, marking them seen.",
    "ast_hotspot": (
        "Rank Python functions/classes by branching complexity and flag swallowed exceptions."
    ),
    "import_impact": (
        "Compute AST transitive reverse-dependency closure, impacted tests, and L0/L2 tier."
    ),
    "trace_locator": (
        "Extract in-repo file:line frames and code windows from a Python traceback or error log."
    ),
    "contract_surface": (
        "Inspect public exports (__all__), function signatures, and verifier-surface guards."
    ),
}

_EXCLUDED_DIRS: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        "build",
        "dist",
        ".evolver",
        ".evomap",
        "memory",
    }
)

_MAX_SCAN_FILES: Final[int] = 60
_MAX_ITEMS: Final[int] = 15


def _resolve_root(repo_root: Path | None = None) -> Path:
    if repo_root is not None:
        return repo_root.resolve()
    found = get_repo_root(_quiet=True)
    return (found or get_workspace_root()).resolve()


def _safe_target_path(root: Path, target: str) -> Path | None:
    raw = (target or ".").strip()
    cand = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
    try:
        cand.relative_to(root)
    except ValueError:
        return None
    return cand if cand.exists() else None


def _collect_py_files(root: Path, target_path: Path) -> list[Path]:
    if target_path.is_file():
        return [target_path] if target_path.suffix == ".py" else []
    files: list[Path] = []
    for cur_root, dirs, fnames in os.walk(target_path):
        dirs[:] = [
            d
            for d in dirs
            if d not in _EXCLUDED_DIRS and not d.endswith(".egg-info") and not d.startswith(".git")
        ]
        rp = Path(cur_root)
        for fn in sorted(fnames):
            if fn.endswith(".py"):
                files.append(rp / fn)
                if len(files) >= _MAX_SCAN_FILES:
                    return files
    return files


def _branch_score(node: ast.AST) -> int:
    branch_types = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Try,
        ast.ExceptHandler,
        ast.With,
        ast.AsyncWith,
        ast.BoolOp,
        ast.IfExp,
    )
    return 1 + sum(1 for child in ast.walk(node) if isinstance(child, branch_types))


def _is_swallowed_handler(handler: ast.ExceptHandler) -> bool:
    if not handler.body:
        return True
    if len(handler.body) == 1:
        stmt = handler.body[0]
        if isinstance(stmt, ast.Pass):
            return True
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            return True
    return False


def _lens_list() -> dict[str, Any]:
    from evolver.gep.asset_store import load_genes

    items: list[dict[str, Any]] = [
        {"name": name, "kind": "builtin", "description": desc}
        for name, desc in BUILTIN_LENSES.items()
    ]
    for gene in load_genes():
        if not isinstance(gene, dict):
            continue
        lens_spec = gene.get("lens")
        if isinstance(lens_spec, dict) or (isinstance(lens_spec, str) and lens_spec.strip()):
            items.append(
                {
                    "name": str(gene.get("id") or ""),
                    "kind": "operator_gene",
                    "description": str(gene.get("summary") or gene.get("description") or "")[:160],
                }
            )
    op_count = len(items) - len(BUILTIN_LENSES)
    return {
        "summary": f"{len(BUILTIN_LENSES)} built-in lenses, {op_count} operator lenses.",
        "items": items[:30],
    }


def _lens_ast_hotspot(root: Path, target: str) -> dict[str, Any]:
    target_path = _safe_target_path(root, target)
    if target_path is None:
        return {
            "ok": False,
            "error": "target_outside_or_missing",
            "summary": f"Target {target!r} does not exist inside {root}.",
            "items": [],
        }
    hotspots: list[dict[str, Any]] = []
    swallowed: list[dict[str, Any]] = []

    for py_file in _collect_py_files(root, target_path):
        rel = py_file.relative_to(root).as_posix()
        try:
            src = py_file.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src, filename=rel)
        except (OSError, SyntaxError):
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                end_line = getattr(node, "end_lineno", node.lineno) or node.lineno
                span = max(1, end_line - node.lineno + 1)
                complexity = _branch_score(node)
                hotspots.append(
                    {
                        "location": f"{rel}:{node.lineno}",
                        "symbol": node.name,
                        "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                        "lines": span,
                        "complexity": complexity,
                    }
                )
            elif isinstance(node, ast.ExceptHandler) and _is_swallowed_handler(node):
                exc_name = ast.unparse(node.type) if node.type is not None else "bare_except"
                swallowed.append(
                    {
                        "location": f"{rel}:{node.lineno}",
                        "exception": exc_name,
                        "issue": "swallowed_exception",
                    }
                )

    hotspots.sort(key=lambda r: (int(r["complexity"]), int(r["lines"])), reverse=True)
    top = hotspots[:_MAX_ITEMS]
    return {
        "summary": (
            f"Scanned AST under {target!r}: {len(hotspots)} symbols, "
            f"{len(swallowed)} swallowed exception handler(s)."
        ),
        "items": top,
        "swallowed_exceptions": swallowed[:_MAX_ITEMS],
    }


def _lens_import_impact(root: Path, target: str, args: dict[str, Any]) -> dict[str, Any]:
    raw_files = args.get("files")
    candidates: list[str] = []
    if isinstance(raw_files, list):
        candidates.extend(str(f) for f in raw_files if str(f).strip())
    if target and target != ".":
        candidates.append(target)
    if not candidates:
        from evolver.gep.git_ops import git_list_changed_files, git_list_untracked_files

        candidates = git_list_changed_files(root) + git_list_untracked_files(root)

    norm_files: list[str] = []
    for f in candidates:
        clean = f.replace("\\", "/").lstrip("./")
        if clean and clean not in norm_files:
            norm_files.append(clean)

    graph = build_or_load_import_graph(root)
    impacted_tests = find_impacted_tests(root, norm_files, graph=graph)
    escalate, esc_reason = requires_l2_escalation(norm_files)
    reverse_deps = graph.get("reverse_deps") or {}
    direct_importers: dict[str, list[str]] = {
        f: list(reverse_deps.get(f, []))[:10] for f in norm_files if f in reverse_deps
    }
    tier = "L2" if escalate else "L0"
    return {
        "summary": (
            f"Impact for {len(norm_files)} file(s): tier={tier}"
            + (f" ({esc_reason})" if esc_reason else "")
            + f", {len(impacted_tests)} impacted test file(s)."
        ),
        "tier": tier,
        "escalation_reason": esc_reason or None,
        "target_files": norm_files[:20],
        "impacted_tests": impacted_tests[:30],
        "direct_importers": direct_importers,
        "items": [{"test": t} for t in impacted_tests[:_MAX_ITEMS]],
    }


_TB_FRAME_RE: Final = re.compile(r'File "([^"]+)", line (\d+)(?:, in ([^\r\n]+))?')
_COLON_LOC_RE: Final = re.compile(r"([A-Za-z0-9_./\\-]+\.py):(\d+)")


def _lens_trace_locator(root: Path, target: str, args: dict[str, Any]) -> dict[str, Any]:
    text = str(args.get("traceback") or args.get("error") or target or "")
    seen: set[tuple[str, int]] = set()
    frames: list[dict[str, Any]] = []

    raw_matches: list[tuple[str, int, str]] = []
    for m in _TB_FRAME_RE.finditer(text):
        raw_matches.append((m.group(1), int(m.group(2)), (m.group(3) or "").strip()))
    for m in _COLON_LOC_RE.finditer(text):
        raw_matches.append((m.group(1), int(m.group(2)), ""))

    for raw_file, lineno, func in raw_matches:
        resolved = _safe_target_path(root, raw_file)
        if resolved is None or not resolved.is_file():
            continue
        rel = resolved.relative_to(root).as_posix()
        key = (rel, lineno)
        if key in seen:
            continue
        seen.add(key)
        try:
            lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        lo = max(1, lineno - 3)
        hi = min(len(lines), lineno + 3)
        snippet = "\n".join(
            f"{'>' if idx == lineno else ' '} {idx:4d} | {lines[idx - 1]}"
            for idx in range(lo, hi + 1)
        )
        frames.append(
            {
                "location": f"{rel}:{lineno}",
                "function": func or None,
                "snippet": snippet,
            }
        )
        if len(frames) >= 8:
            break

    return {
        "summary": f"Located {len(frames)} in-repo frame(s).",
        "items": frames,
    }


def _lens_contract_surface(root: Path, target: str) -> dict[str, Any]:
    target_path = _safe_target_path(root, target)
    if target_path is None:
        return {
            "ok": False,
            "error": "target_outside_or_missing",
            "summary": f"Target {target!r} does not exist inside {root}.",
            "items": [],
        }
    items: list[dict[str, Any]] = []
    for py_file in _collect_py_files(root, target_path)[:20]:
        rel = py_file.relative_to(root).as_posix()
        verifier_guarded = any(
            rel == surf or rel.startswith(surf) for surf in ANCHOR_TRIGGER_SURFACES
        )
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"), filename=rel)
        except (OSError, SyntaxError):
            continue
        exports: list[str] = []
        public_defs: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if (
                        isinstance(t, ast.Name)
                        and t.id == "__all__"
                        and isinstance(node.value, ast.List | ast.Tuple | ast.Set)
                    ):
                        exports.extend(
                            str(elt.value)
                            for elt in node.value.elts
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        )
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                if not node.name.startswith("_"):
                    public_defs.append(node.name)
        items.append(
            {
                "file": rel,
                "anchor_verifier_surface": verifier_guarded,
                "dunder_all": exports[:25],
                "public_symbols": public_defs[:25],
            }
        )
    guarded_count = sum(1 for row in items if row["anchor_verifier_surface"])
    return {
        "summary": (
            f"Inspected {len(items)} module(s) under {target!r} "
            f"({guarded_count} guarded by out-of-repo Anchor probes)."
        ),
        "items": items,
    }


def _redact_payload(obj: Any) -> Any:
    """Ensure sealed validation strings never leak out of a lens response."""
    from evolver.gep.val_seal import redact

    if isinstance(obj, str):
        clean, _ = redact(obj, where="dispatch")
        return clean
    if isinstance(obj, list):
        return [_redact_payload(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _redact_payload(v) for k, v in obj.items()}
    return obj


def _lens_card(root: Path, target: str, args: dict[str, Any]) -> dict[str, Any]:
    from evolver.gep.operator_cards import render_cards_for_lens

    return render_cards_for_lens(target, args, repo_root=root)


def _active_operator_maps() -> tuple[dict[str, dict[str, Any]], dict[str, list[str]], set[str]]:
    from evolver.gep.asset_store import load_genes
    from evolver.gep.gene_lifecycle import load_lifecycle_sets

    retired_ids, _under_review = load_lifecycle_sets()
    by_id: dict[str, dict[str, Any]] = {}
    dep_graph: dict[str, list[str]] = {}
    for g in load_genes():
        if not isinstance(g, dict):
            continue
        gid = str(g.get("id") or "").strip()
        if not gid:
            continue
        by_id[gid] = g
        deps = [
            str(d).strip()
            for d in (g.get("builds_on") or g.get("dependencies") or [])
            if str(d).strip()
        ]
        if deps:
            dep_graph[gid] = deps
    return by_id, dep_graph, set(retired_ids)


def _execute_operator_lens(
    root: Path,
    matched: dict[str, Any],
    lens_spec: Any,
    target: str,
    extra: dict[str, Any],
    *,
    depth: int,
) -> dict[str, Any]:
    if isinstance(lens_spec, dict) and str(lens_spec.get("builtin") or "") in BUILTIN_LENSES:
        delegated = str(lens_spec["builtin"])
        return _run_lens_inner(
            delegated,
            target=target or str(lens_spec.get("default_target") or "."),
            args={**(lens_spec.get("args") or {}), **extra},
            repo_root=root,
            depth=depth + 1,
        )

    code = (
        lens_spec
        if isinstance(lens_spec, str)
        else (str(lens_spec.get("code") or "") if isinstance(lens_spec, dict) else "")
    )
    if not code.strip():
        return {
            "ok": False,
            "error": "empty_operator_lens",
            "summary": f"Operator {matched.get('id')!r} defines no executable lens code.",
            "items": [],
        }

    from evolver.gep.operator_sandbox import SandboxLensContext, run_lens_code_sandboxed

    by_id, dep_graph, retired_ids = _active_operator_maps()
    known_lenses = set(BUILTIN_LENSES) | set(by_id)
    declared_deps = [
        str(d).strip()
        for d in (matched.get("builds_on") or matched.get("dependencies") or [])
        if str(d).strip()
    ]
    raw_slots = extra.get("slots")
    slot_overrides = (
        {str(k): str(v) for k, v in raw_slots.items()} if isinstance(raw_slots, dict) else None
    )

    def _nested_call(
        dep_name: str,
        dep_target: str = ".",
        dep_args: dict[str, Any] | None = None,
        next_depth: int = 1,
    ) -> dict[str, Any]:
        return _run_lens_inner(
            dep_name,
            target=dep_target,
            args=dep_args,
            repo_root=root,
            depth=next_depth,
        )

    ctx = SandboxLensContext(root, call_lens_fn=_nested_call, depth=depth)
    return run_lens_code_sandboxed(
        code,
        ctx=ctx,
        target=target,
        args=extra,
        slot_overrides=slot_overrides,
        operator_id=str(matched.get("id") or ""),
        operator_kind=(str(matched.get("operator_kind")) if matched.get("operator_kind") else None),
        declared_deps=declared_deps,
        known_lenses=known_lenses,
        retired_ids=retired_ids,
        dep_graph=dep_graph,
    )


def _run_lens_inner(
    name: str = "list",
    target: str = ".",
    args: dict[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
    depth: int = 0,
) -> dict[str, Any]:
    from evolver.gep.operator_sandbox import MAX_COMPOSITION_DEPTH

    t0 = time.monotonic()
    lens_name = (name or "list").strip()
    extra = dict(args) if isinstance(args, dict) else {}
    root = _resolve_root(repo_root)

    if depth > MAX_COMPOSITION_DEPTH:
        return {
            "ok": False,
            "read_only": True,
            "error": "composition_depth_exceeded",
            "lens": lens_name,
            "target": target,
            "duration_ms": 0,
            "summary": f"Lens composition depth exceeded {MAX_COMPOSITION_DEPTH}.",
            "items": [],
        }

    if lens_name == "list":
        body = _lens_list()
    elif lens_name == "card":
        body = _lens_card(root, target, extra)
    elif lens_name == "ast_hotspot":
        body = _lens_ast_hotspot(root, target)
    elif lens_name == "import_impact":
        body = _lens_import_impact(root, target, extra)
    elif lens_name == "trace_locator":
        body = _lens_trace_locator(root, target, extra)
    elif lens_name == "contract_surface":
        body = _lens_contract_surface(root, target)
    else:
        from evolver.gep.asset_store import load_genes

        matched = next(
            (g for g in load_genes() if isinstance(g, dict) and str(g.get("id")) == lens_name),
            None,
        )
        lens_spec = matched.get("lens") if isinstance(matched, dict) else None
        if isinstance(matched, dict) and lens_spec is not None:
            body = _execute_operator_lens(root, matched, lens_spec, target, extra, depth=depth)
        else:
            duration_ms = round((time.monotonic() - t0) * 1000)
            avail_str = ", ".join(sorted(BUILTIN_LENSES))
            return {
                "ok": False,
                "read_only": True,
                "error": "unknown_lens",
                "lens": lens_name,
                "target": target,
                "duration_ms": duration_ms,
                "available_lenses": sorted(BUILTIN_LENSES),
                "summary": f"Unknown lens {lens_name!r}. Choose from: {avail_str}.",
                "items": [],
            }

    duration_ms = round((time.monotonic() - t0) * 1000)
    ok = bool(body.get("ok", True))
    envelope: dict[str, Any] = {
        "ok": ok,
        "read_only": True,
        "lens": lens_name,
        "target": target,
        "duration_ms": duration_ms,
        **body,
    }
    res: dict[str, Any] = _redact_payload(envelope)
    return res


def run_lens(
    name: str = "list",
    target: str = ".",
    args: dict[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Execute a read-only diagnostic lens and return a bounded JSON envelope."""
    return _run_lens_inner(name=name, target=target, args=args, repo_root=repo_root, depth=0)


__all__ = ["BUILTIN_LENSES", "run_lens"]
