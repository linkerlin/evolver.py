"""Anchor probe: validation env normalization + bounded output (DEBUG #22).

GUI-spawned hosts propagate a minimal PATH; validation must prepend the
toolchain dirs (never drop entries). Failed-gate evidence must retain the
pytest failure summary, which lives at the END of stdout.
Exit 0 = pass.
"""

from __future__ import annotations

import os
import sys
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
    ws = Path("/tmp/anchor-probe-validation-env")
    ws.mkdir(parents=True, exist_ok=True)
    _isolate(ws)
    from evolver.gep.validation_env import validation_env
    from evolver.gep.solidify import _bounded_output

    os.environ["PATH"] = "/usr/bin:/bin"
    env = validation_env()
    parts = env["PATH"].split(os.pathsep)
    if parts[0] != str(Path(sys.executable).parent):
        print(f"FAIL: venv bin not prepended: {parts[0]}")
        return 1
    if "/usr/bin" not in parts:
        print("FAIL: inherited entries dropped")
        return 1

    long_text = "A" * 5000 + "B" * 5000 + "\nFAILED tests/x.py"
    bounded = _bounded_output(long_text)
    if "FAILED tests/x.py" not in bounded or not bounded.startswith("A" * 10):
        print("FAIL: bounded output lost head or tail")
        return 1
    if _bounded_output("short") != "short":
        print("FAIL: short output mangled")
        return 1
    print("PASS: env normalized, evidence head+tail retained")
    return 0


if __name__ == "__main__":
    sys.exit(main())
