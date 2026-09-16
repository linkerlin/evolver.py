"""Anchor probe: HITL fail-closed semantics (DEBUG #12).

Unknown EVOLVER_HITL_MODE values parse as ON; a corrupt approvals store
refuses skip-validation rather than silently clearing the gate.
Exit 0 = pass.
"""

from __future__ import annotations

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
        from evolver.config import parse_hitl_mode

        if parse_hitl_mode("disabled") != "on":
            print("FAIL: unknown mode must fail closed to on")
            return 1
        if parse_hitl_mode("ON") != "on" or parse_hitl_mode("1") != "on":
            print("FAIL: canonical on-values must parse on")
            return 1

        evo = ws / "memory" / "evolution"
        evo.mkdir(parents=True, exist_ok=True)
        (evo / "hitl_approvals.json").write_text("{corrupt", encoding="utf-8")
        os.environ["EVOLVER_HITL_MODE"] = "on"
        import importlib
        import evolver.config as config_mod

        importlib.reload(config_mod)
        from evolver.gep.solidify import solidify, write_state_for_solidify

        write_state_for_solidify(
            {
                "run_id": "run_anchor_hitl",
                "signals": ["log_error"],
                "selected_gene_id": "g_anchor",
                "mutation": {"id": "m_anchor", "validation": []},
            }
        )
        result = solidify(skip_validation=True)
        if result.get("ok") or not str(result.get("error", "")).startswith("hitl_"):
            print(f"FAIL: corrupt store must refuse skip, got {result.get('error')}")
            return 1
        print("PASS: HITL unknown-mode=on, corrupt store refuses skip")
        return 0


if __name__ == "__main__":
    sys.exit(main())
