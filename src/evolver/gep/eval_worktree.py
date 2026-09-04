"""S26.5 — evaluate mutations in a clean git worktree.

wikiskill isolates scoring in a sandbox so leftover live-tree dirt (runtime
JSONL, failed leftovers) cannot affect the gate. This is the git-native
equivalent: ``git worktree add --detach`` from HEAD, overlay only non-runtime
working-tree files, run the cascade/acceptance cwd there, then remove.

Flag ``enable_eval_worktree`` (default off). Any setup failure falls back to
the live cwd so soak is never blocked by isolation itself.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from evolver.gep.feature_flags import is_enabled
from evolver.gep.git_ops import (
    git_list_changed_files,
    git_list_untracked_files,
    is_git_repo,
    run_cmd,
)

logger = logging.getLogger(__name__)

_RUNTIME_HEADS: frozenset[str] = frozenset(
    {".evolver", ".evolver_settings", ".evomap", ".pytest_cache", "logs", "memory"}
)


def is_runtime_rel(rel: str) -> bool:
    """True for engine runtime paths that must not enter the eval tree."""
    norm = rel.replace("\\", "/")
    head = norm.split("/", 1)[0]
    return head in _RUNTIME_HEADS or norm.startswith("evolver/.config/")


def _overlay_mutation(src: Path, dest: Path) -> None:
    files = set(git_list_changed_files(src) + git_list_untracked_files(src))
    for rel in files:
        if is_runtime_rel(rel):
            continue
        src_p = src / rel
        if not src_p.is_file():
            continue
        dest_p = dest / rel
        dest_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_p, dest_p)


@contextmanager
def isolated_eval_cwd(src: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Yield ``(eval_cwd, meta)``; always cleans up a created worktree."""
    if not is_enabled("enable_eval_worktree"):
        yield src, {"isolated": False, "reason": "flag_off"}
        return
    if not is_git_repo(src):
        yield src, {"isolated": False, "reason": "not_a_git_repo"}
        return

    dest = Path(tempfile.gettempdir()) / f"evolver-eval-{uuid.uuid4().hex[:12]}"
    added = False
    eval_path = src
    meta: dict[str, Any] = {"isolated": False, "reason": "fallback"}
    try:
        run_cmd(["worktree", "add", "--detach", str(dest), "HEAD"], cwd=src)
        added = True
        _overlay_mutation(src, dest)
        eval_path = dest
        meta = {"isolated": True, "reason": "worktree", "path": str(dest)}
    except Exception as exc:
        logger.warning("eval worktree unavailable (%s); using live cwd", exc)
        meta = {
            "isolated": False,
            "reason": f"fallback:{type(exc).__name__}",
            "error": str(exc)[:200],
        }
        eval_path = src
    try:
        yield eval_path, meta
    finally:
        if added:
            try:
                run_cmd(["worktree", "remove", "--force", str(dest)], cwd=src)
            except Exception:
                shutil.rmtree(dest, ignore_errors=True)
        elif dest.exists():
            shutil.rmtree(dest, ignore_errors=True)


__all__ = ["is_runtime_rel", "isolated_eval_cwd"]
