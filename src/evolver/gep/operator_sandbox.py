"""Zero-network controlled operator sandbox & DAG composition audit (P2-1 + S-2).

Enforces static AST safety and runtime resource bounds for executable
``OperatorGene.v1`` payloads:
- Static AST audit blocks network, subprocess, dynamic code execution, and
  destructive filesystem primitives.
- Composed DAG audit verifies ``builds_on`` / ``dependencies`` against actual
  ``ctx.call_lens("<name>", ...)`` AST calls (no undeclared calls, no unused
  declarations, no retired/missing targets, no cycles).
- Runtime execution strips API credentials/secrets, enforces a strict ``< 2s``
  timeout, and restricts file reads strictly under ``repo_root``.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any, Final

from evolver.gep.operator_slots import render_with_overrides

MAX_OPERATOR_TIMEOUT_S: Final[float] = 2.0
MAX_COMPOSITION_DEPTH: Final[int] = 4
_MAX_SCAN_FILES: Final[int] = 80
_MAX_FILE_BYTES: Final[int] = 256_000

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

FORBIDDEN_IMPORTS: Final[frozenset[str]] = frozenset(
    {
        "aiohttp",
        "ctypes",
        "fcntl",
        "ftplib",
        "http",
        "httpx",
        "importlib",
        "marshal",
        "multiprocessing",
        "pickle",
        "pty",
        "requests",
        "shutil",
        "socket",
        "subprocess",
        "sys",
        "telnetlib",
        "urllib",
        "webbrowser",
    }
)

FORBIDDEN_CALL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "__import__",
        "breakpoint",
        "compile",
        "eval",
        "exec",
        "open",
    }
)

FORBIDDEN_ATTR_CALLS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("os", "popen"),
        ("os", "remove"),
        ("os", "rename"),
        ("os", "replace"),
        ("os", "rmdir"),
        ("os", "system"),
        ("os", "unlink"),
    }
)

FORBIDDEN_METHOD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "rmdir",
        "unlink",
        "write_bytes",
        "write_text",
    }
)

_SENSITIVE_KEY_RE: Final = re.compile(
    r"(?:_API_KEY|_APIKEY|_API_TOKEN|_SECRET|_PASSWORD|_OAUTH|ANTHROPIC_|OPENAI_|DEEPSEEK_)",
    re.IGNORECASE,
)


def scrub_operator_env(base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return a copy of *base_env* stripped of all API keys, secrets, and tokens."""
    source = os.environ if base_env is None else base_env
    return {k: str(v) for k, v in source.items() if not _SENSITIVE_KEY_RE.search(str(k))}


def extract_called_lenses(tree: ast.AST) -> list[str]:
    """Extract unique literal lens names called via ``ctx.call_lens("<name>", ...)``."""
    called: list[str] = []
    seen: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "call_lens"):
            continue
        name_val: str | None = None
        if (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            name_val = node.args[0].value.strip()
        else:
            for kw in node.keywords:
                if (
                    kw.arg == "name"
                    and isinstance(kw.value, ast.Constant)
                    and isinstance(kw.value.value, str)
                ):
                    name_val = kw.value.value.strip()
                    break
        if name_val and name_val not in seen:
            seen.add(name_val)
            called.append(name_val)
    return called


def detect_operator_dag_cycle(
    operator_id: str,
    deps: Sequence[str],
    dep_graph: Mapping[str, Sequence[str]],
) -> list[str] | None:
    """Return cycle path if adding ``operator_id -> deps`` introduces a cycle, else None."""
    graph: dict[str, list[str]] = {str(k): [str(d) for d in v] for k, v in dep_graph.items()}
    graph[operator_id] = [str(d) for d in deps]

    visiting: set[str] = set()
    visited: set[str] = set()

    def _dfs(node: str, trail: list[str]) -> list[str] | None:
        if node in visiting:
            idx = trail.index(node)
            return trail[idx:]
        if node in visited:
            return None
        visiting.add(node)
        for nxt in graph.get(node, ()):
            cyc = _dfs(nxt, [*trail, nxt])
            if cyc is not None:
                return cyc
        visiting.remove(node)
        visited.add(node)
        return None

    return _dfs(operator_id, [operator_id])


def audit_operator_ast(
    source: str,
    *,
    operator_id: str = "",
    operator_kind: str | None = None,
    declared_deps: Sequence[str] = (),
    known_lenses: AbstractSet[str] | None = None,
    retired_ids: AbstractSet[str] | None = None,
    dep_graph: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """Statically audit Python operator code for sandbox safety and DAG consistency."""
    violations: list[str] = []
    if not isinstance(source, str) or not source.strip():
        return {"ok": False, "violations": ["empty operator source"], "called_lenses": []}
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {
            "ok": False,
            "violations": [f"SyntaxError: {exc.msg} (line {exc.lineno})"],
            "called_lenses": [],
        }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_pkg = alias.name.split(".", 1)[0]
                if root_pkg in FORBIDDEN_IMPORTS:
                    violations.append(f"forbidden import `{alias.name}`")
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".", 1)[0]
            if mod in FORBIDDEN_IMPORTS:
                violations.append(f"forbidden import from `{node.module}`")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALL_NAMES:
                violations.append(f"forbidden call `{func.id}()`")
            elif isinstance(func, ast.Attribute):
                if (
                    isinstance(func.value, ast.Name)
                    and (func.value.id, func.attr) in FORBIDDEN_ATTR_CALLS
                ):
                    violations.append(f"forbidden call `{func.value.id}.{func.attr}()`")
                if func.attr in FORBIDDEN_METHOD_NAMES:
                    violations.append(f"forbidden mutating method `.{func.attr}()`")

    called = extract_called_lenses(tree)
    declared = [str(d).strip() for d in declared_deps if str(d).strip()]
    declared_set = set(declared)
    called_set = set(called)

    if operator_kind == "composed" and not declared:
        violations.append("composed operator must declare non-empty `builds_on` / `dependencies`")

    if declared or called:
        missing_calls = sorted(declared_set - called_set)
        undeclared_calls = sorted(called_set - declared_set)
        if missing_calls:
            violations.append(
                f"declared dependencies never called via ctx.call_lens: {', '.join(missing_calls)}"
            )
        if undeclared_calls:
            joined = ", ".join(undeclared_calls)
            violations.append(f"undeclared ctx.call_lens targets missing from builds_on: {joined}")

    if known_lenses is not None:
        unknown = sorted(d for d in declared_set if d not in known_lenses)
        if unknown:
            violations.append(f"unknown dependency lens(es): {', '.join(unknown)}")

    if retired_ids is not None:
        retired_hits = sorted(d for d in declared_set if d in retired_ids)
        if retired_hits:
            violations.append(
                f"dependency references retired operator(s): {', '.join(retired_hits)}"
            )

    if operator_id and declared:
        cycle = detect_operator_dag_cycle(operator_id, declared, dep_graph or {})
        if cycle:
            violations.append(f"composition cycle detected: {' -> '.join(cycle)}")

    return {
        "ok": len(violations) == 0,
        "violations": violations,
        "called_lenses": called,
        "declared_deps": declared,
    }


class SandboxLensContext:
    """Read-only, repo-confined runtime context passed into executable operator lenses."""

    def __init__(
        self,
        repo_root: Path,
        *,
        call_lens_fn: Callable[[str, str, dict[str, Any] | None, int], dict[str, Any]],
        depth: int = 0,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self._call_lens_fn = call_lens_fn
        self._depth = depth

    def resolve_safe(self, rel_or_path: str) -> Path | None:
        raw = (rel_or_path or ".").strip()
        cand = (
            (self.repo_root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        )
        try:
            cand.relative_to(self.repo_root)
        except ValueError:
            return None
        return cand if cand.exists() else None

    def iter_py_files(self, target: str = ".", *, limit: int = _MAX_SCAN_FILES) -> list[str]:
        target_path = self.resolve_safe(target)
        if target_path is None:
            return []
        if target_path.is_file():
            return (
                [target_path.relative_to(self.repo_root).as_posix()]
                if target_path.suffix == ".py"
                else []
            )
        out: list[str] = []
        cap = min(_MAX_SCAN_FILES, max(1, int(limit)))
        for cur_root, dirs, fnames in os.walk(target_path):
            dirs[:] = [
                d
                for d in dirs
                if d not in _EXCLUDED_DIRS
                and not d.endswith(".egg-info")
                and not d.startswith(".git")
            ]
            rp = Path(cur_root)
            for fn in sorted(fnames):
                if fn.endswith(".py"):
                    out.append((rp / fn).relative_to(self.repo_root).as_posix())
                    if len(out) >= cap:
                        return out
        return out

    def read_text(self, rel_path: str, *, max_bytes: int = _MAX_FILE_BYTES) -> str:
        safe = self.resolve_safe(rel_path)
        if safe is None or not safe.is_file():
            return ""
        raw = safe.read_bytes()[: max(1, min(_MAX_FILE_BYTES, int(max_bytes)))]
        return raw.decode("utf-8", errors="replace")

    def call_lens(
        self,
        name: str,
        target: str = ".",
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._depth >= MAX_COMPOSITION_DEPTH:
            return {
                "ok": False,
                "error": "composition_depth_exceeded",
                "summary": f"Composition depth exceeded {MAX_COMPOSITION_DEPTH}.",
                "items": [],
            }
        return self._call_lens_fn(name, target, args, self._depth + 1)


_SAFE_BUILTINS: Final[dict[str, Any]] = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "frozenset": frozenset,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "range": range,
    "reversed": reversed,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}


def _restricted_import(
    name: str,
    globals_dict: Any = None,
    locals_dict: Any = None,
    fromlist: Any = (),
    level: int = 0,
) -> Any:
    root_pkg = str(name or "").split(".", 1)[0]
    if root_pkg not in {"ast", "json", "math", "re", "collections", "dataclasses"}:
        raise ImportError(f"Sandbox forbids import of `{name}`")
    return __import__(name, globals_dict, locals_dict, fromlist, level)


def run_lens_code_sandboxed(
    source: str,
    *,
    ctx: SandboxLensContext,
    target: str = ".",
    args: dict[str, Any] | None = None,
    slot_overrides: Mapping[str, str] | None = None,
    operator_id: str = "",
    operator_kind: str | None = None,
    declared_deps: Sequence[str] = (),
    known_lenses: AbstractSet[str] | None = None,
    retired_ids: AbstractSet[str] | None = None,
    dep_graph: Mapping[str, Sequence[str]] | None = None,
    timeout_s: float = MAX_OPERATOR_TIMEOUT_S,
) -> dict[str, Any]:
    """Audit, instantiate slot overrides, and execute a read-only ``lens(ctx, target, args)``."""
    audit = audit_operator_ast(
        source,
        operator_id=operator_id,
        operator_kind=operator_kind,
        declared_deps=declared_deps,
        known_lenses=known_lenses,
        retired_ids=retired_ids,
        dep_graph=dep_graph,
    )
    if not audit["ok"]:
        return {
            "ok": False,
            "error": "sandbox_audit_failed",
            "summary": "; ".join(audit["violations"]),
            "violations": audit["violations"],
            "items": [],
        }

    try:
        effective_source = render_with_overrides(source, slot_overrides)
    except ValueError as exc:
        return {
            "ok": False,
            "error": "invalid_slot_overrides",
            "summary": str(exc),
            "items": [],
        }

    # Re-audit post-override source so injected slot templates cannot mutate structure.
    post_audit = audit_operator_ast(
        effective_source,
        operator_id=operator_id,
        operator_kind=operator_kind,
        declared_deps=declared_deps,
        known_lenses=known_lenses,
        retired_ids=retired_ids,
        dep_graph=dep_graph,
    )
    if not post_audit["ok"]:
        return {
            "ok": False,
            "error": "sandbox_post_override_audit_failed",
            "summary": "; ".join(post_audit["violations"]),
            "violations": post_audit["violations"],
            "items": [],
        }

    namespace: dict[str, Any] = {
        "__builtins__": {**_SAFE_BUILTINS, "__import__": _restricted_import},
    }
    try:
        compiled = compile(effective_source, f"<operator:{operator_id or 'lens'}>", "exec")
        exec(compiled, namespace)
    except Exception as exc:
        return {
            "ok": False,
            "error": "operator_compile_failed",
            "summary": f"{type(exc).__name__}: {exc}",
            "items": [],
        }

    fn = namespace.get("lens") or namespace.get("run")
    if not callable(fn):
        return {
            "ok": False,
            "error": "missing_lens_entrypoint",
            "summary": "Operator lens code must define callable `lens(ctx, target, args)`.",
            "items": [],
        }

    extra_args = dict(args or {})
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn, ctx, target, extra_args)
    try:
        res = future.result(timeout=max(0.1, min(MAX_OPERATOR_TIMEOUT_S, float(timeout_s))))
    except FuturesTimeoutError:
        return {
            "ok": False,
            "error": "operator_timeout",
            "summary": f"Operator lens exceeded {timeout_s:.1f}s timeout.",
            "items": [],
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": "operator_runtime_error",
            "summary": f"{type(exc).__name__}: {exc}",
            "items": [],
        }
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if not isinstance(res, dict):
        return {
            "ok": False,
            "error": "invalid_operator_return",
            "summary": "Operator lens must return a dict.",
            "items": [],
        }
    return dict(res)


def run_invariant_probe_sandboxed(
    probe_code: str,
    *,
    cwd: Path,
    timeout_s: float = MAX_OPERATOR_TIMEOUT_S,
) -> dict[str, Any]:
    """Execute a minimal invariant assertion snippet in an isolated, scrubbed subprocess."""
    audit = audit_operator_ast(probe_code)
    if not audit["ok"]:
        return {
            "ok": False,
            "error": "invariant_audit_failed",
            "violations": audit["violations"],
            "duration_ms": 0,
        }
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", probe_code],
            cwd=str(cwd),
            env=scrub_operator_env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(0.1, min(MAX_OPERATOR_TIMEOUT_S, float(timeout_s))),
            shell=False,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-1000:],
            "stderr": (proc.stderr or "")[-1000:],
            "duration_ms": round((time.monotonic() - t0) * 1000),
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "invariant_timeout",
            "duration_ms": round((time.monotonic() - t0) * 1000),
        }
    except OSError as exc:
        return {
            "ok": False,
            "error": f"invariant_exec_failed: {exc}",
            "duration_ms": round((time.monotonic() - t0) * 1000),
        }


__all__ = [
    "FORBIDDEN_ATTR_CALLS",
    "FORBIDDEN_CALL_NAMES",
    "FORBIDDEN_IMPORTS",
    "FORBIDDEN_METHOD_NAMES",
    "MAX_COMPOSITION_DEPTH",
    "MAX_OPERATOR_TIMEOUT_S",
    "SandboxLensContext",
    "audit_operator_ast",
    "detect_operator_dag_cycle",
    "extract_called_lenses",
    "run_invariant_probe_sandboxed",
    "run_lens_code_sandboxed",
    "scrub_operator_env",
]
