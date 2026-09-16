"""Anchor probe: pending-solidify truth (DEBUG #9).

True iff state holds a last_run newer than the last solidify; corrupt state
fails TOWARD solidify. File existence alone must never report pending.
Exit 0 = pass.
"""

from __future__ import annotations

import json
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
        _isolate(ws)
        from evolver.gep.paths import get_solidify_state_path
        from evolver.swarm import _pending_solidify_state

        path = get_solidify_state_path()
        # 1. no file -> False
        if _pending_solidify_state() is not False:
            print("FAIL: missing state file must report not-pending")
            return 1
        # 2. last_run != last_solidify -> True
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"last_run": {"run_id": "r_a"}, "last_solidify": {"run_id": "r_b"}}),
            encoding="utf-8",
        )
        if _pending_solidify_state() is not True:
            print("FAIL: newer last_run must report pending")
            return 1
        # 3. equal -> False
        path.write_text(
            json.dumps({"last_run": {"run_id": "r_a"}, "last_solidify": {"run_id": "r_a"}}),
            encoding="utf-8",
        )
        if _pending_solidify_state() is not False:
            print("FAIL: landed run must report not-pending")
            return 1
        # 4. corrupt -> True (fail toward solidify)
        path.write_text("{not json", encoding="utf-8")
        if _pending_solidify_state() is not True:
            print("FAIL: corrupt state must fail toward solidify")
            return 1
        print("PASS: pending truth = run-id comparison, corrupt fails safe")
        return 0


if __name__ == "__main__":
    sys.exit(main())
