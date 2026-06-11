"""Git CLI helpers, diff snapshots, rollback.

Equivalent to evolver/src/gep/gitOps.js.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

CRITICAL_PROTECTED_PREFIXES = (
    ".env",
    ".git/",
)

CRITICAL_PROTECTED_FILES = (
    ".env",
    ".gitignore",
    "package.json",
    "package-lock.json",
    "pyproject.toml",
    "uv.lock",
)


def run_cmd(
    args: Sequence[str], cwd: Path | str | None = None, timeout: float | None = None
) -> str:
    """Run a git command and return stripped stdout. Raises on non-zero exit."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return result.stdout.strip()


def try_run_cmd(
    args: Sequence[str],
    cwd: Path | str | None = None,
    timeout: float | None = None,
    default: str = "",
) -> str:
    try:
        return run_cmd(args, cwd=cwd, timeout=timeout)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return default


def is_git_repo(cwd: Path | str | None = None) -> bool:
    try:
        run_cmd(["rev-parse", "--git-dir"], cwd=cwd)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False


def normalize_rel_path(path: str) -> str:
    """Strip leading ./ and normalize separators."""
    p = path.replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p


def count_file_lines(path: Path | str) -> int:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def git_list_changed_files(cwd: Path | str | None = None) -> list[str]:
    raw = try_run_cmd(["diff", "--name-only", "HEAD"], cwd=cwd)
    return [line for line in raw.splitlines() if line.strip()]


def git_list_untracked_files(cwd: Path | str | None = None) -> list[str]:
    raw = try_run_cmd(["ls-files", "--others", "--exclude-standard"], cwd=cwd)
    return [line for line in raw.splitlines() if line.strip()]


def capture_diff_snapshot(
    cwd: Path | str | None = None,
    max_chars: int = 80_000,
) -> str:
    """Capture current diff vs HEAD, truncated to max_chars."""
    raw = try_run_cmd(["diff", "HEAD"], cwd=cwd)
    if len(raw) > max_chars:
        return raw[:max_chars] + "\n...[truncated]\n"
    return raw


def is_critical_protected_path(rel_path: str) -> bool:
    p = normalize_rel_path(rel_path)
    if p in CRITICAL_PROTECTED_FILES:
        return True
    for prefix in CRITICAL_PROTECTED_PREFIXES:
        if p.startswith(prefix):
            return True
    return False


def is_constraint_counted_path(rel_path: str) -> bool:
    """Returns True for paths that should count toward blast-radius limits."""
    p = normalize_rel_path(rel_path)
    if is_critical_protected_path(p):
        return False
    ignored_prefixes = (
        ".git/",
        "node_modules/",
        ".venv/",
        "venv/",
        "__pycache__/",
        ".pytest_cache/",
    )
    return not any(p.startswith(prefix) for prefix in ignored_prefixes)


def rollback_tracked(
    mode: str | None = None,
    cwd: Path | str | None = None,
) -> dict[str, Any]:
    """Roll back tracked changes according to EVOLVER_ROLLBACK_MODE."""
    if mode is None:
        mode = os.environ.get("EVOLVER_ROLLBACK_MODE", "stash").lower().strip()

    result = {"mode": mode, "ok": False, "error": None}
    try:
        if mode == "hard":
            run_cmd(["reset", "--hard", "HEAD"], cwd=cwd)
            result["ok"] = True
        elif mode == "stash":
            run_cmd(["stash", "push", "--include-untracked", "-m", "evolver rollback"], cwd=cwd)
            result["ok"] = True
        elif mode == "none":
            result["ok"] = True
        else:
            result["error"] = f"Unknown rollback mode: {mode}"
    except subprocess.CalledProcessError as exc:
        result["error"] = str(exc)
    return result


def rollback_new_untracked_files(files: Sequence[str], cwd: Path | str | None = None) -> None:
    """Best-effort remove newly created untracked files."""
    root = Path(cwd) if cwd else Path.cwd()
    for rel in files:
        path = root / rel
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass
