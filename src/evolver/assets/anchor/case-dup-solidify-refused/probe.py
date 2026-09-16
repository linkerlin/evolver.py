"""Anchor probe: duplicate solidify refused (DEBUG #19).

Frozen out-of-tree contract. A re-solidify on an already-landed run must
early-return already_solidified — never burn a cascade nor append a phantom
success event that pollutes the acceptance soak sample.
Exit 0 = pass. Self-contained: builds an isolated workspace.
"""

from __future__ import annotations

import json
import os
import subprocess
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


def _git(ws: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(ws), *args], check=True, capture_output=True, text=True)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / "ws"
        ws.mkdir()
        _isolate(ws)
        _git(ws, "init")
        _git(ws, "config", "user.email", "anchor@test.local")
        _git(ws, "config", "user.name", "anchor")
        (ws / "README.md").write_text("init\n", encoding="utf-8")
        _git(ws, "add", "-A")
        _git(ws, "-c", "commit.gpgsign=false", "commit", "-m", "init")

        from evolver.gep.solidify import solidify, write_state_for_solidify

        run = {
            "run_id": "run_anchor_dup",
            "signals": ["log_error"],
            "selected_gene_id": "g_anchor",
            "mutation": {"id": "m_anchor", "validation": []},
        }
        write_state_for_solidify(run)
        first = solidify(skip_validation=True)
        if not first.get("ok"):
            print(f"FAIL: first solidify should succeed, got {first.get('error')}")
            return 1
        second = solidify(skip_validation=True)
        if second.get("ok") or second.get("error") != "already_solidified":
            print(f"FAIL: expected already_solidified, got {json.dumps(second)[:300]}")
            return 1
        print("PASS: duplicate solidify refused with already_solidified")
        return 0


if __name__ == "__main__":
    sys.exit(main())
