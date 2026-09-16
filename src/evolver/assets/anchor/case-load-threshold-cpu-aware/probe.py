"""Anchor probe: CPU-aware preflight load threshold (DEBUG #24).

A flat 1.5 permanently blocked multi-core hosts at ambient GUI load; the
default must track the core count (queue deeper than cores aborts).
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
    ws = Path("/tmp/anchor-probe-load")
    ws.mkdir(parents=True, exist_ok=True)
    _isolate(ws)
    from evolver.evolve import guards

    guards.detect_cpu_count = lambda: 1
    if guards.get_default_load_max() != 0.9:
        print("FAIL: single-core default changed")
        return 1
    guards.detect_cpu_count = lambda: 10
    if guards.get_default_load_max() != 10.0:
        print(f"FAIL: 10-core default should be 10.0, got {guards.get_default_load_max()}")
        return 1
    print("PASS: load threshold scales with CPU count")
    return 0


if __name__ == "__main__":
    sys.exit(main())
