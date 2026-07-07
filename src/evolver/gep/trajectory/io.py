"""Trajectory I/O — read trace rows and write trajectories safely.

Ports the ``writeTrajectories`` safety contract from
``evolver/test/trajectoryExport.test.js`` (PR #294 C4):

* atomic write (temp file + ``os.replace`` in the same directory),
* a pre-placed symlink at the output path is **not followed** — it is replaced
  by a fresh regular file so a symlink attack cannot clobber the link target,
* the output file is owner-only (mode ``0o600`` on POSIX).

This slice reads plaintext proxy-trace JSONL. Encrypted-row decryption and the
non-proxy session-log sources are deferred to a later slice.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from evolver.gep.trajectory.builder import Trajectory, build_trajectories


def trajectory_to_dict(traj: Trajectory) -> dict[str, Any]:
    """Serialise a :class:`Trajectory` to a plain dict (one JSONL record)."""
    return asdict(traj)


def read_trace_rows(input_path: Path) -> list[dict[str, Any]]:
    """Read plaintext JSONL trace rows (one row per line). Skips blank/invalid lines."""
    rows: list[dict[str, Any]] = []
    for raw in Path(input_path).read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        with contextlib.suppress(ValueError):
            row = json.loads(stripped)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _atomic_write_text(path: Path, content: str) -> None:
    """Write *content* to *path* atomically, owner-only, never via a symlink.

    If *path* exists as a symlink it is removed first so the write lands in a
    fresh regular file (PR #294 C4 — a pre-placed symlink must not be followed).
    """
    # Refuse to follow a pre-placed symlink: unlink it so the temp+replace
    # below creates a brand-new regular file at this path.
    with contextlib.suppress(OSError):
        if path.is_symlink():
            path.unlink()

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        _chmod_owner_only(tmp)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    # os.replace preserves the temp file's mode; re-assert owner-only in case
    # the target existed as a regular file with broader permissions.
    _chmod_owner_only(path)


def _chmod_owner_only(path: Path) -> None:
    if os.name != "nt":
        with contextlib.suppress(OSError):
            path.chmod(0o600)


def write_trajectories_to_path(output_path: Path, trajectories: list[Trajectory]) -> None:
    """Write *trajectories* (one JSON object per line) to *output_path* safely."""
    lines = [json.dumps(trajectory_to_dict(t), ensure_ascii=False) for t in trajectories]
    _atomic_write_text(Path(output_path), "\n".join(lines) + ("\n" if lines else ""))


def write_trajectories(*, input_path: Path | str, output_path: Path | str) -> list[Trajectory]:
    """Read trace rows from *input_path*, build trajectories, write to *output_path*.

    Returns the built trajectories.
    """
    rows = read_trace_rows(Path(input_path))
    trajectories = build_trajectories(rows)
    write_trajectories_to_path(Path(output_path), trajectories)
    return trajectories
