"""S26.5 — evaluate mutations in a clean git worktree.

wikiskill isolates scoring in a sandbox so leftover live-tree dirt (runtime
JSONL, failed leftovers) cannot affect the gate. This is the git-native
equivalent: ``git worktree add --detach`` from HEAD, overlay only non-runtime
working-tree files, run the cascade/acceptance cwd there, then remove.

Flag ``enable_eval_worktree`` (default on). Any setup failure falls back to
the live cwd so soak is never blocked by isolation itself.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import sys
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

DEFAULT_WHITELIST_DOC_GLOBS: tuple[str, ...] = (
    "*方案*.md",
    "TODO*.md",
    "CHANGELOG.md",
    "DEBUG.md",
    "AGENTS.md",
)


def is_runtime_rel(rel: str) -> bool:
    """True for engine runtime paths that must not enter the eval tree."""
    norm = rel.replace("\\", "/")
    head = norm.split("/", 1)[0]
    return head in _RUNTIME_HEADS or norm.startswith("evolver/.config/")


def check_dirty_runtime(src: Path) -> list[str]:
    """Return uncommitted untracked runtime files in src that violate hermeticity."""
    try:
        untracked = git_list_untracked_files(src)
        return [u for u in untracked if is_runtime_rel(u)]
    except Exception:
        return []


def _whitelist_doc_globs() -> list[str]:
    globs = list(DEFAULT_WHITELIST_DOC_GLOBS)
    extra = os.environ.get("EVOLVER_EVAL_WORKTREE_WHITELIST", "")
    if extra.strip():
        for part in extra.split(","):
            if part.strip() and part.strip() not in globs:
                globs.append(part.strip())
    return globs


def _overlay_mutation(src: Path, dest: Path) -> list[str]:
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

    # U-9: Overlay whitelisted gitignored stage documents (e.g. *方案*.md)
    overlaid_docs: list[str] = []
    for pattern in _whitelist_doc_globs():
        for match in sorted(src.glob(pattern)):
            if not match.is_file():
                continue
            rel_str = match.relative_to(src).as_posix()
            if is_runtime_rel(rel_str):
                continue
            dest_p = dest / rel_str
            if not dest_p.exists():
                dest_p.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(match, dest_p)
                overlaid_docs.append(rel_str)
    return overlaid_docs


def inspect_test_referenced_untracked_docs(src: Path, dest: Path) -> list[str]:
    """U-9: Report root-level docs referenced by tests in ``src`` missing in ``dest``."""
    tests_dir = src / "tests"
    if not tests_dir.is_dir():
        return []
    referenced: set[str] = set()
    doc_re = re.compile(r"""['"]([^'"/\\]+\.md)['"]""")
    for test_file in tests_dir.rglob("test_*.py"):
        try:
            text = test_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in doc_re.findall(text):
            referenced.add(match)

    missing: list[str] = []
    for name in sorted(referenced):
        if (src / name).is_file() and not (dest / name).is_file():
            missing.append(name)
            logger.warning(
                "[eval_worktree] Test-referenced doc %r exists in live tree "
                "but is missing in eval worktree",
                name,
            )
    return missing


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
        overlaid_docs = _overlay_mutation(src, dest)
        missing_docs = inspect_test_referenced_untracked_docs(src, dest)
        eval_path = dest
        meta = {
            "isolated": True,
            "reason": "worktree",
            "path": str(dest),
            "overlaid_whitelist_docs": overlaid_docs,
            "missing_untracked_docs": missing_docs,
        }
    except Exception as exc:
        if os.getenv("EVOLVER_EVAL_WORKTREE_STRICT") in {"1", "true", "yes"}:
            raise RuntimeError(f"eval_worktree strict isolation failed: {exc}") from exc
        dirty = check_dirty_runtime(src)
        warn_msg = f"[eval_worktree] WARNING: worktree isolation failed ({exc}); using live cwd"
        if dirty:
            warn_msg += f" (live tree dirty with {len(dirty)} runtime files)"
        logger.warning(warn_msg)
        print(warn_msg, file=sys.stderr)
        meta = {
            "isolated": False,
            "reason": f"fallback:{type(exc).__name__}",
            "error": str(exc)[:200],
            "dirty_runtime": dirty,
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


__all__ = [
    "DEFAULT_WHITELIST_DOC_GLOBS",
    "check_dirty_runtime",
    "inspect_test_referenced_untracked_docs",
    "is_runtime_rel",
    "isolated_eval_cwd",
]
