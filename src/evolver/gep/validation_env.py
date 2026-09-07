"""Shared subprocess environment for engine-spawned validation processes.

Extracted from :mod:`evolver.gep.solidify` (round-14): the acceptance gate
spawns its own pytest subprocesses (T0 discovery / repeats) and needs the
same PATH normalization as the validation cascade — GUI-spawned MCP hosts
propagate the launchd minimal PATH, bare ``pytest`` lookups fail there, and
``gate_or_none`` degrades the exception to ``None`` (gate silently disabled,
soak sample stops growing). One helper, two consumers.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def validation_env() -> dict[str, str]:
    """Subprocess env for validation/acceptance commands.

    Never drops entries; prepends the well-known toolchain dirs (existing
    ones only) so the repo's own toolchain resolves regardless of how the
    engine process was spawned.
    """
    env = dict(os.environ)
    parts = [p for p in env.get("PATH", "").split(os.pathsep) if p]
    known = [
        str(Path(sys.executable).parent),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        str(Path.home() / ".local" / "bin"),
    ]
    for directory in reversed(known):
        if directory not in parts and Path(directory).is_dir():
            parts.insert(0, directory)
    env["PATH"] = os.pathsep.join(parts)
    return env


__all__ = ["validation_env"]
