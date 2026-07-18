"""Trajectory export — group proxy traces into coding trajectories (G10.1).

Foundation slice of the v1.90.0 multi-source trajectory export. See
:mod:`evolver.gep.trajectory.builder` and :mod:`evolver.gep.trajectory.io`.
"""

from __future__ import annotations

from evolver.gep.trajectory.builder import (
    Trajectory,
    TrajectoryStats,
    Turn,
    build_trajectories,
    build_trajectory_from_rows,
)
from evolver.gep.trajectory.crypto import (
    TraceDecryptError,
    decrypt_trace_row,
    derive_node_key,
    read_trace_rows_detailed,
)
from evolver.gep.trajectory.inputs import read_trajectory_inputs_detailed
from evolver.gep.trajectory.io import (
    read_trace_rows,
    trajectory_to_dict,
    write_trajectories,
    write_trajectories_to_path,
)
from evolver.gep.trajectory.marked_gate import collect_runtime_session_inputs
from evolver.gep.trajectory.sources import (
    build_claude_code_trajectory,
    build_codex_trajectory,
    build_generic_chat_trajectory,
    build_trajectory_from_session_log,
    detect_source,
)

__all__ = [
    "TraceDecryptError",
    "Trajectory",
    "TrajectoryStats",
    "Turn",
    "build_claude_code_trajectory",
    "build_codex_trajectory",
    "build_generic_chat_trajectory",
    "build_trajectories",
    "build_trajectory_from_rows",
    "build_trajectory_from_session_log",
    "collect_runtime_session_inputs",
    "decrypt_trace_row",
    "derive_node_key",
    "detect_source",
    "read_trace_rows",
    "read_trace_rows_detailed",
    "read_trajectory_inputs_detailed",
    "trajectory_to_dict",
    "write_trajectories",
    "write_trajectories_to_path",
]
