"""In-process candidate isolation for Python module surfaces.

Methodology inspired by Self-Harness (arXiv:2606.09498,
``harbor_wrapper.py`` ``_candidate_import_context``). No Node.js equivalent;
evolver.py self-research addition (Sprint A2).

Evaluating many harness variants in one process requires that each candidate's
module imports load ITS version, not a stale cached one. This context manager
snapshots ``sys.path``, evicts the target module(s) from ``sys.modules``,
prepends the candidate workspace, and restores everything on exit.

Non-Python changes fall back to out-of-process (git worktree / sequential)
handling — see :func:`is_python_surface_change`.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SurfaceModule = Any


@contextmanager
def candidate_import_context(
    candidate_workspace: Path,
    module_names: list[str],
) -> Iterator[None]:
    """Load *module_names* from *candidate_workspace* for the block duration.

    On exit, ``sys.path`` and ``sys.modules`` are restored exactly.
    """
    workspace = str(candidate_workspace)
    old_path = list(sys.path)
    evicted: list[str] = []
    for name in module_names:
        if name in sys.modules:
            evicted.append(name)
            del sys.modules[name]

    sys.path.insert(0, workspace)
    try:
        yield
    finally:
        sys.path[:] = old_path
        for name in evicted:
            sys.modules[name] = importlib.import_module(name)


def load_candidate_module(
    candidate_workspace: Path,
    module_name: str,
) -> SurfaceModule:
    """Import *module_name* from *candidate_workspace* (isolated).

    Returns the module object; ``sys.path``/``sys.modules`` are restored after
    import (the module object itself is returned for the caller to use).
    """
    workspace = str(candidate_workspace)
    old_path = list(sys.path)
    evicted = module_name in sys.modules
    if evicted:
        del sys.modules[module_name]
    try:
        sys.path.insert(0, workspace)
        return importlib.import_module(module_name)
    finally:
        sys.path[:] = old_path
        if evicted:
            sys.modules[module_name] = importlib.import_module(module_name)


def is_python_surface_change(changed_files: list[str]) -> bool:
    """True iff any changed file is a ``.py`` module surface.

    Non-Python changes (docs, configs, other languages) cannot be isolated
    in-process and must fall back to out-of-process handling.
    """
    return any(rel.endswith(".py") for rel in changed_files)


__all__ = [
    "candidate_import_context",
    "is_python_surface_change",
    "load_candidate_module",
]
