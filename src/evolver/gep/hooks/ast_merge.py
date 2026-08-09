"""Function-level AST merge with conflict detection.

Methodology inspired by Self-Harness (arXiv:2606.09498,
``run_self_harness_loop.py`` ``merge_candidate_changes``). No Node.js
equivalent; evolver.py self-research addition (Sprint C3).

Merges multiple accepted candidates onto a base source file at the granularity
of **top-level functions** only:

* deletions of top-level functions are rejected,
* changes to non-function top-level code (imports, assignments) are rejected,
* two candidates editing the same top-level function raise
  :class:`MergeConflict` (never silently overwritten),
* new functions are inserted following the candidate's top-level order
  (after their predecessor, or at the top when no predecessor exists in the
  target).

This deliberately restricted surface turns N accepted candidates into one
coherent branch safely. Non-Python files / class methods fall back to
sequential application elsewhere (Sprint C3 plan note).
"""

from __future__ import annotations

import ast
from typing import Any


class MergeConflict(Exception):
    """Raised when candidates overlap or the edit violates merge constraints."""


def top_level_function_spans(source: str) -> dict[str, tuple[int, int]]:
    """Map top-level function name → ``(start, end)`` 1-indexed inclusive line
    span (decorators included). Throws :class:`SyntaxError` on invalid source.
    """
    tree = ast.parse(source)
    spans: dict[str, tuple[int, int]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            if node.decorator_list:
                start = min(d.lineno for d in node.decorator_list)
            end = node.end_lineno or node.lineno
            spans[node.name] = (start, end)
    return spans


def top_level_order(source: str) -> list[str]:
    """Top-level function names in source order."""
    tree = ast.parse(source)
    return [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _slice(source: str, start: int, end: int) -> str:
    lines = source.splitlines()
    return "\n".join(lines[start - 1 : end])


def function_sources(
    source: str, spans: dict[str, tuple[int, int]]
) -> dict[str, str]:
    """Map function name → its source text (decorators included)."""
    return {name: _slice(source, start, end) for name, (start, end) in spans.items()}


def _without_functions(
    source: str, spans: dict[str, tuple[int, int]]
) -> str:
    """Source with all top-level function spans removed (blank line kept)."""
    lines = source.splitlines()
    covered: set[int] = set()
    for start, end in spans.values():
        covered.update(range(start - 1, min(end, len(lines))))
    return "\n".join("" if i in covered else line for i, line in enumerate(lines))


def changed_top_level_functions(base: str, candidate: str) -> list[str]:
    """Top-level functions whose source differs between *base* and *candidate*.

    Raises :class:`MergeConflict` when *candidate* deletes a top-level function
    or modifies non-function top-level code (imports/assignments).
    """
    base_spans = top_level_function_spans(base)
    cand_spans = top_level_function_spans(candidate)

    deleted = set(base_spans) - set(cand_spans)
    if deleted:
        raise MergeConflict(
            f"deleted top-level function(s): {sorted(deleted)}"
        )

    if _without_functions(base, base_spans) != _without_functions(
        candidate, cand_spans
    ):
        raise MergeConflict("non-function top-level code changed")

    base_funcs = function_sources(base, base_spans)
    cand_funcs = function_sources(candidate, cand_spans)
    return [
        name
        for name in base_funcs
        if name in cand_funcs and base_funcs[name] != cand_funcs[name]
    ]


def _insert_line(target: str, name: str, cand_order: list[str]) -> int:
    """1-indexed line before which to insert a new function *name*."""
    spans = top_level_function_spans(target)
    try:
        idx = cand_order.index(name)
    except ValueError:
        return 1
    for prev in reversed(cand_order[:idx]):
        if prev in spans:
            return spans[prev][1] + 1
    return 1


def apply_function_definition(
    target: str,
    name: str,
    new_source: str,
    *,
    cand_order: list[str] | None = None,
) -> str:
    """Replace (or insert) top-level function *name* in *target*.

    When *name* is new to *target*, the function is inserted after its
    predecessor in *cand_order* (or at the top when none exists).
    """
    spans = top_level_function_spans(target)
    lines = target.splitlines()
    new_lines = new_source.splitlines()

    if name in spans:
        start, end = spans[name]
        lines[start - 1 : end] = new_lines
        return "\n".join(lines)

    insert_at = _insert_line(target, name, cand_order or [])
    lines[insert_at - 1 : insert_at - 1] = new_lines
    return "\n".join(lines)


def merge_candidate_changes(base: str, candidates: list[str]) -> str:
    """Merge top-level function changes from *candidates* onto *base*.

    Raises :class:`MergeConflict` on deletions, non-function top-level edits,
    or two candidates editing the same function. New functions are inserted
    following each candidate's top-level order.
    """
    working = base
    base_spans = top_level_function_spans(base)
    base_funcs = function_sources(base, base_spans)

    for candidate in candidates:
        changed = changed_top_level_functions(base, candidate)
        cand_spans = top_level_function_spans(candidate)
        cand_funcs = function_sources(candidate, cand_spans)
        cand_order = top_level_order(candidate)

        working_spans = top_level_function_spans(working)
        working_funcs = function_sources(working, working_spans)

        for name in changed:
            # Another candidate already changed this function → conflict.
            if (
                name in working_funcs
                and working_funcs[name] != base_funcs[name]
            ):
                raise MergeConflict(
                    f"conflicting edits to function {name!r}"
                )
            working = apply_function_definition(
                working,
                name,
                cand_funcs[name],
                cand_order=cand_order,
            )
    return working


__all__ = [
    "MergeConflict",
    "apply_function_definition",
    "changed_top_level_functions",
    "function_sources",
    "merge_candidate_changes",
    "top_level_function_spans",
    "top_level_order",
]
