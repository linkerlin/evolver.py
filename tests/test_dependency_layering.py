"""S30 dependency layering — core engine imports must stay light.

fastapi/uvicorn live in the optional `server` extra; importing the core
modules (cli / mcp_server / swarm) in a fresh interpreter must not pull them
into sys.modules. Enforces the lazy-import discipline even where the dev
environment has the server stack installed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_core_imports_avoid_server_stack(tmp_path: Path) -> None:
    code = (
        "import sys; "
        "import evolver.cli, evolver.mcp_server, evolver.swarm; "
        "leaked = [m for m in ('fastapi', 'uvicorn') if m in sys.modules]; "
        "print(','.join(leaked))"
    )
    env = {**os.environ, "EVOLVER_NO_PARENT_GIT": "1", "EVOLVER_REPO_ROOT": str(tmp_path)}
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "", f"server deps leaked into core: {proc.stdout}"
