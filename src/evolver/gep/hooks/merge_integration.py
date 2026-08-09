"""Contract-driven merge of multiple accepted candidates.

Methodology inspired by Self-Harness (arXiv:2606.09498). No Node.js
equivalent; evolver.py self-research addition (Sprint C3).

Consumes ``ctx["accepted_candidates"]`` — a list of
``{"path", "base", "candidate"}`` dicts (materialized candidates that passed
the Sprint A1 acceptance gate, produced by the Sprint A2 materialization
layer). Groups by ``path``, merges each group with
:func:`evolver.gep.hooks.ast_merge.merge_candidate_changes`, and reports
conflicts per path instead of raising (the caller decides what to do).

Per-path merge result: ``{"path", "merged_source" | None, "conflict" | None}``.
"""

from __future__ import annotations

from typing import Any

from evolver.gep.hooks.ast_merge import MergeConflictError, merge_candidate_changes


def merge_accepted_candidates(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge *candidates* per ``path``; conflicts are reported, not raised.

    Entries missing ``path``/``base``/``candidate`` are skipped. Empty input
    yields an empty list.
    """
    by_path: dict[str, dict[str, Any]] = {}
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        path = cand.get("path")
        base = cand.get("base")
        candidate_src = cand.get("candidate")
        if not path or not isinstance(base, str) or not isinstance(candidate_src, str):
            continue
        group = by_path.setdefault(path, {"base": base, "candidates": []})
        group["candidates"].append(candidate_src)

    out: list[dict[str, Any]] = []
    for path, group in by_path.items():
        try:
            merged = merge_candidate_changes(group["base"], group["candidates"])
            out.append({"path": path, "merged_source": merged, "conflict": None})
        except MergeConflictError as exc:
            out.append({"path": path, "merged_source": None, "conflict": str(exc)})
    return out


__all__ = ["merge_accepted_candidates"]
