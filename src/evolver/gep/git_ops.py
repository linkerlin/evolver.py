"""Git CLI helpers, diff snapshots, rollback.

Equivalent to evolver/src/gep/gitOps.js.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from evolver.solo.git_guard import guard_git_subcommand

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
    # Solo local-git-only guard: refuse network subcommands at the choke point.
    blocked = guard_git_subcommand(args[0] if args else None)
    if blocked:
        raise RuntimeError(blocked)
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
    return any(p.startswith(prefix) for prefix in CRITICAL_PROTECTED_PREFIXES)


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
    *,
    include_untracked: bool = True,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Roll back tracked changes according to EVOLVER_ROLLBACK_MODE.

    ``include_untracked=False`` (Sprint 23): stash tracked changes only —
    untracked disposal is the caller's business (the fitness-cascade /
    novelty paths delete untracked files selectively so engine state dirs
    that the workspace does not gitignore survive the rollback).
    """
    if mode is None:
        mode = os.environ.get("EVOLVER_ROLLBACK_MODE", "stash").lower().strip()

    stash_msg = f"evolver: rejected {run_id}" if run_id else "evolver: rejected"
    result: dict[str, Any] = {
        "mode": mode,
        "ok": False,
        "error": None,
        "stash_message": None,
    }
    try:
        if mode == "hard":
            run_cmd(["reset", "--hard", "HEAD"], cwd=cwd)
            result["ok"] = True
        elif mode == "stash":
            argv = ["stash", "push", "-m", stash_msg]
            if include_untracked:
                argv.insert(3, "--include-untracked")
            out = run_cmd(argv, cwd=cwd)
            result["ok"] = True
            result["stash_message"] = stash_msg
            result["stash_output"] = out
        elif mode == "none":
            result["ok"] = True
        else:
            result["error"] = f"Unknown rollback mode: {mode}"
    except subprocess.CalledProcessError as exc:
        result["error"] = str(exc)
    return result


def snapshot_rejected_worktree(
    cwd: Path | str | None = None,
    *,
    run_id: str | None = None,
    disposable_untracked: Sequence[str] | None = None,
    reason: str = "rejected",
) -> dict[str, Any]:
    """Save a recoverable snapshot (diff + untracked files) before rollback/stash (U-4)."""
    from evolver.gep.paths import get_evolution_dir

    root = Path(cwd) if cwd else Path.cwd()
    rid = str(run_id or "latest").strip() or "latest"
    diff_text = try_run_cmd(["diff", "HEAD"], cwd=root)
    untracked_list = (
        list(disposable_untracked)
        if disposable_untracked is not None
        else git_list_untracked_files(root)
    )
    untracked_blobs: dict[str, str] = {}
    for rel in untracked_list:
        fpath = root / rel
        try:
            if fpath.is_file():
                untracked_blobs[rel] = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

    stash_dir = get_evolution_dir() / "rejected_stashes"
    stash_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "run_id": rid,
        "reason": reason,
        "cwd": str(root.resolve()),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "diff": diff_text,
        "untracked_files": untracked_blobs,
    }
    target = stash_dir / f"{rid}.json"
    latest = stash_dir / "latest.json"
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        target.write_text(serialized, encoding="utf-8")
        latest.write_text(serialized, encoding="utf-8")
    except OSError:
        pass
    return {
        "ok": True,
        "saved": True,
        "run_id": rid,
        "snapshot_path": str(target),
        "has_diff": bool(diff_text.strip()),
        "untracked_count": len(untracked_blobs),
    }


def restore_rejected_stash(
    cwd: Path | str | None = None,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Restore the most recent rejected mutation from git stash or snapshot backup (U-4)."""
    from evolver.gep.paths import get_evolution_dir

    root = Path(cwd) if cwd else Path.cwd()
    stash_dir = get_evolution_dir() / "rejected_stashes"
    rid = str(run_id or "").strip()
    snap_path = (stash_dir / f"{rid}.json") if rid else (stash_dir / "latest.json")
    snapshot: dict[str, Any] | None = None
    if snap_path.is_file():
        try:
            loaded = json.loads(snap_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                snapshot = loaded
        except (OSError, json.JSONDecodeError):
            snapshot = None

    restored_via_git_stash = False
    stash_ref: str | None = None
    if is_git_repo(root):
        stash_list = try_run_cmd(["stash", "list"], cwd=root)
        needle = f"evolver: rejected {rid}" if rid else "evolver: rejected"
        for line in stash_list.splitlines():
            if needle in line or (not rid and "evolver rollback" in line):
                stash_ref = line.split(":", 1)[0].strip()
                break
        if stash_ref:
            try:
                run_cmd(["stash", "pop", stash_ref], cwd=root)
                restored_via_git_stash = True
            except subprocess.CalledProcessError:
                try:
                    run_cmd(["stash", "apply", stash_ref], cwd=root)
                    restored_via_git_stash = True
                except subprocess.CalledProcessError:
                    restored_via_git_stash = False

    restored_untracked: list[str] = []
    restored_via_patch = False
    if snapshot is not None:
        if not restored_via_git_stash:
            diff_text = str(snapshot.get("diff") or "")
            if diff_text.strip():
                patch_file = stash_dir / "_restore.patch"
                try:
                    patch_file.write_text(diff_text, encoding="utf-8")
                    run_cmd(["apply", "--whitespace=nowarn", str(patch_file)], cwd=root)
                    restored_via_patch = True
                except (OSError, subprocess.CalledProcessError):
                    restored_via_patch = False
                finally:
                    try:
                        if patch_file.is_file():
                            patch_file.unlink()
                    except OSError:
                        pass
        untracked_map = snapshot.get("untracked_files")
        if isinstance(untracked_map, dict):
            for rel, content in untracked_map.items():
                dest = root / str(rel)
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(str(content), encoding="utf-8")
                    restored_untracked.append(str(rel))
                except OSError:
                    continue

    ok = bool(restored_via_git_stash or restored_via_patch or restored_untracked)
    if not ok:
        return {
            "ok": False,
            "error": "no_rejected_stash_found",
            "cwd": str(root),
            "run_id": rid or None,
        }
    return {
        "ok": True,
        "action": "restored_stash",
        "cwd": str(root),
        "run_id": (snapshot or {}).get("run_id") or rid or None,
        "restored_via_git_stash": restored_via_git_stash,
        "stash_ref": stash_ref,
        "restored_via_patch": restored_via_patch,
        "restored_untracked": restored_untracked,
    }


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
