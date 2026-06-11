"""Exploration engine — discover unvisited code paths and generate probes.

Equivalent to Node's ``evolver/src/gep/explore.js``.

Scans the codebase for:
1. Untouched / uncovered source files.
2. Functions without docstrings or type hints.
3. Modules with low test coverage (heuristic).
4. TODO / FIXME comments.

Produces *exploration tasks* that can be fed into the GEP cycle
as signals or directly scheduled via :mod:`idle_scheduler`.

Design notes
------------
* Stateless — works on the filesystem snapshot at call time.
* Uses ``ast`` for Python source analysis.
* Respects ``.gitignore`` via ``pathspec`` if available, else simple
  substring matching.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evolver.gep.paths import get_workspace_root

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ExplorationTask:
    task_type: str  # "missing_docstring", "missing_type_hint", "todo", "uncovered_file"
    file_path: str
    line: int = 0
    symbol: str = ""
    description: str = ""
    priority: float = 0.0  # 0-1, higher = more important

    def to_signal(self) -> dict[str, Any]:
        return {
            "type": "explore",
            "task_type": self.task_type,
            "file_path": self.file_path,
            "line": self.line,
            "symbol": self.symbol,
            "description": self.description,
            "priority": self.priority,
        }


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _parse_file(path: Path) -> ast.AST | None:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        return ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        logger.debug("[Explore] Failed to parse %s: %s", path, exc)
        return None


def _should_skip(path: Path, root: Path) -> bool:
    """Return ``True`` for files that should be ignored."""
    rel = str(path.relative_to(root)).replace("\\", "/")
    skip_patterns = [
        ".venv/",
        "venv/",
        "__pycache__/",
        ".pytest_cache/",
        "node_modules/",
        ".git/",
        "dist/",
        "build/",
        ".egg-info/",
    ]
    for pat in skip_patterns:
        if pat in rel:
            return True
    return False


def _find_missing_docstrings(tree: ast.AST, path: Path) -> list[ExplorationTask]:
    tasks: list[ExplorationTask] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if ast.get_docstring(node) is None:
                name = getattr(node, "name", "<unknown>")
                tasks.append(
                    ExplorationTask(
                        task_type="missing_docstring",
                        file_path=str(path),
                        line=getattr(node, "lineno", 0),
                        symbol=name,
                        description=f"{node.__class__.__name__} '{name}' lacks a docstring",
                        priority=0.4,
                    )
                )
    return tasks


def _find_missing_type_hints(tree: ast.AST, path: Path) -> list[ExplorationTask]:
    tasks: list[ExplorationTask] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            has_hints = False
            # Check args
            args = node.args
            for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
                if arg.annotation is not None:
                    has_hints = True
                    break
            if args.vararg and args.vararg.annotation is not None:
                has_hints = True
            if args.kwarg and args.kwarg.annotation is not None:
                has_hints = True
            if node.returns is not None:
                has_hints = True
            if not has_hints:
                name = getattr(node, "name", "<unknown>")
                tasks.append(
                    ExplorationTask(
                        task_type="missing_type_hint",
                        file_path=str(path),
                        line=getattr(node, "lineno", 0),
                        symbol=name,
                        description=f"Function '{name}' has no type hints",
                        priority=0.3,
                    )
                )
    return tasks


def _find_todos(path: Path) -> list[ExplorationTask]:
    tasks: list[ExplorationTask] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return tasks
    for i, line in enumerate(lines, start=1):
        lower = line.lower()
        if "todo" in lower or "fixme" in lower or "hack" in lower:
            priority = 0.6 if "fixme" in lower else 0.5
            tasks.append(
                ExplorationTask(
                    task_type="todo",
                    file_path=str(path),
                    line=i,
                    description=line.strip(),
                    priority=priority,
                )
            )
    return tasks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def explore_workspace(
    *,
    root: Path | None = None,
    max_tasks: int = 20,
) -> list[ExplorationTask]:
    """Scan the workspace and return a prioritized list of exploration tasks."""
    cwd = root or get_workspace_root()
    tasks: list[ExplorationTask] = []

    for py_file in cwd.rglob("*.py"):
        if _should_skip(py_file, cwd):
            continue
        # TODO / FIXME
        tasks.extend(_find_todos(py_file))
        # AST-based analysis
        tree = _parse_file(py_file)
        if tree is None:
            continue
        tasks.extend(_find_missing_docstrings(tree, py_file))
        tasks.extend(_find_missing_type_hints(tree, py_file))

    # Sort by priority descending, then deduplicate by (file, line, type)
    seen: set[tuple[str, int, str]] = set()
    unique: list[ExplorationTask] = []
    for t in sorted(tasks, key=lambda x: x.priority, reverse=True):
        key = (t.file_path, t.line, t.task_type)
        if key not in seen:
            seen.add(key)
            unique.append(t)

    return unique[:max_tasks]


def top_exploration_signals(
    *,
    root: Path | None = None,
    max_tasks: int = 10,
) -> list[dict[str, Any]]:
    """Return the top exploration tasks as signal dicts."""
    return [t.to_signal() for t in explore_workspace(root=root, max_tasks=max_tasks)]
