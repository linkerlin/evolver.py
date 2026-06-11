"""Shared path resolution for adapter runtime scripts."""

from __future__ import annotations

import subprocess
from pathlib import Path


def find_workspace_root(cwd: Path | str | None = None) -> Path:
    """Find the nearest workspace root containing a git repo."""
    start = Path(cwd) if cwd else Path.cwd()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception:
        pass
    return start
