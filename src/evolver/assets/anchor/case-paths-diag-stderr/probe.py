"""Anchor probe: paths diagnostics channel discipline (DEBUG #21).

Library-level prints on stdout broke every CLI --json contract; diagnostics
must use stderr so machine pipes stay parseable.
Exit 0 = pass.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

def _isolate(ws: Path) -> None:
    (ws / "memory" / "evolution").mkdir(parents=True, exist_ok=True)
    (ws / ".evolver" / "gep").mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "OPENCLAW_WORKSPACE": str(ws),
            "EVOLVER_REPO_ROOT": str(ws),
            "EVOLVER_NO_PARENT_GIT": "1",
            "MEMORY_DIR": str(ws / "memory"),
            "EVOLUTION_DIR": str(ws / "memory" / "evolution"),
            "GEP_ASSETS_DIR": str(ws / ".evolver" / "gep"),
            "EVOLVER_HOME": str(ws / ".evomap"),
            "EVOLVER_SETTINGS_DIR": str(ws / ".evolver_settings"),
            "EVOLVER_LOGS_DIR": str(ws / "logs"),
        }
    )

def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "ws"
        ws.mkdir()
        (ws / ".git").mkdir()
        _isolate(ws)
        os.environ["EVOLVER_QUIET_PARENT_GIT"] = "0"
        os.environ.pop("EVOLVER_REPO_ROOT", None)
        os.environ.pop("EVOLVER_NO_PARENT_GIT", None)
        import subprocess as sp

        probe = (
            "import sys, io, contextlib\n"
            "sys.path.insert(0, '')\n"
            "out, err = io.StringIO(), io.StringIO()\n"
            "import os\n"
            f"os.chdir({str(ws)!r})\n"
            "os.environ.pop('EVOLVER_REPO_ROOT', None)\n"
            "os.environ['EVOLVER_QUIET_PARENT_GIT'] = '0'\n"
            "from evolver.gep.paths import get_repo_root\n"
            "with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):\n"
            "    root = get_repo_root()\n"
            "assert root is not None\n"
            "assert out.getvalue() == '', 'stdout polluted: ' + out.getvalue()[:200]\n"
            "assert 'Using host git repository' in err.getvalue()\n"
            "print('ok')\n"
        )
        proc = sp.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )
        if proc.returncode != 0:
            print(f"FAIL: {proc.stdout[-300:]} {proc.stderr[-300:]}")
            return 1
        print("PASS: diagnostics on stderr, stdout clean")
        return 0


if __name__ == "__main__":
    sys.exit(main())
