"""Unified trajectory input reader (Slice 3b facade).

Mirrors Node ``readTrajectoryInputsDetailed`` for session-log sources used by
the adapter tests. Proxy-trace decryption remains in :mod:`crypto`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from evolver.gep.trajectory.builder import Trajectory
from evolver.gep.trajectory.cursor_vscdb import (
    build_cursor_trajectories_from_vscdb,
    is_cursor_vscdb_path,
)
from evolver.gep.trajectory.gemini_cli import (
    build_gemini_cli_trajectory_from_path,
    is_gemini_cli_path,
)
from evolver.gep.trajectory.kimi_wire import (
    build_kimi_wire_trajectory_from_path,
    is_kimi_wire_path,
)
from evolver.gep.trajectory.marked_gate import collect_runtime_session_inputs
from evolver.gep.trajectory.sources import build_trajectory_from_session_log


def _trajectories_for_path(path: Path) -> list[Trajectory]:
    if is_cursor_vscdb_path(path):
        return build_cursor_trajectories_from_vscdb(path)
    if is_gemini_cli_path(path):
        t = build_gemini_cli_trajectory_from_path(path)
        return [t] if t is not None else []
    if is_kimi_wire_path(path):
        t = build_kimi_wire_trajectory_from_path(path)
        return [t] if t is not None else []
    t = build_trajectory_from_session_log(path)
    return [t] if t is not None else []


def read_trajectory_inputs_detailed(
    file_path: str | Path | None = None,
    opts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read session trajectories from *file_path* and/or runtime discovery opts.

    Returns ``{sessionTrajectories, discovery?}`` (Node field names preserved
    for contract parity with the JS tests).
    """
    opts = opts or {}
    trajectories: list[Trajectory] = []
    discovery: dict[str, Any] | None = None

    if file_path is not None:
        p = Path(file_path)
        trajectories.extend(_trajectories_for_path(p))

    if (
        opts.get("runtimeSessions")
        or opts.get("runtime_sessions")
        or opts.get("runtimeSessionDirs")
    ):
        discovered = collect_runtime_session_inputs(opts)
        discovery = discovered.get("discovery")
        for entry in discovered.get("files") or []:
            path = Path(entry["path"] if isinstance(entry, dict) else entry)
            if file_path is not None and Path(file_path).resolve() == path.resolve():
                continue
            trajectories.extend(_trajectories_for_path(path))

    return {
        "sessionTrajectories": trajectories,
        "discovery": discovery,
    }


__all__ = ["read_trajectory_inputs_detailed"]
