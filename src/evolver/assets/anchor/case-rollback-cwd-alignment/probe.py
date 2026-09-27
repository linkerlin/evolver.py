"""Anchor probe: rollback cwd alignment (DEBUG #20/#23).

The legacy validation-failure path listed untracked files in the workspace
but deleted them from Path.cwd(); under a real-repo cascade that deleted the
engine's own runtime state. The victim file at the workspace-relative path
under an unrelated process cwd must survive a failing solidify.
Exit 0 = pass.
"""

from __future__ import annotations

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


def _run(tmp: str) -> int:
    ws = Path(tmp) / "ws"
    proc_cwd = Path(tmp) / "proccwd"
    ws.mkdir()
    _isolate(ws)
    os.environ["EVOLVER_FF_ENABLE_FITNESS_CASCADE"] = "0"
    _git(ws, "init")
    _git(ws, "config", "user.email", "anchor@test.local")
    _git(ws, "config", "user.name", "anchor")
    (ws / "README.md").write_text("init\n", encoding="utf-8")
    _git(ws, "add", "-A")
    _git(ws, "-c", "commit.gpgsign=false", "commit", "-m", "init")

    victim_dir = proc_cwd / "memory" / "evolution"
    victim_dir.mkdir(parents=True)
    victim = victim_dir / "evolution_solidify_state.json"
    victim.write_text("{}", encoding="utf-8")
    os.chdir(proc_cwd)

    from evolver.gep.hypothesis import record_hypothesis
    from evolver.gep.solidify import solidify, write_state_for_solidify

    # §5.3 — the hypothesis gate runs before validation. The refusal under
    # test is validation_failed's rollback alignment, not the hypothesis
    # gate, so the probe declares the Candidate's claim first. No pack is
    # frozen here, so the ref check defers (any id passes field discipline).
    record_hypothesis(
        {
            "hypothesis": "the repair gene resolves the collected error signal",
            "dimension": "content",
            "mechanism_family": "anchor-fixture",
            "target_hook": "gep.solidify",
            "mechanism_check": [
                {
                    "id": "log_error",
                    "before": "error signal collected with no candidate response",
                    "after": "candidate's validation commands run and fail",
                }
            ],
        }
    )

    write_state_for_solidify(
        {
            "run_id": "run_anchor_rollback",
            "signals": ["log_error"],
            "selected_gene_id": "g_anchor",
            "mutation": {
                "id": "m_anchor",
                "validation": [[sys.executable, "-c", "import sys; sys.exit(1)"]],
            },
        }
    )
    result = solidify()
    if result.get("ok") or result.get("error") != "validation_failed":
        print(f"FAIL: expected validation_failed, got {result.get('error')}")
        return 1
    if not victim.exists():
        print("FAIL: victim state file deleted from process cwd — regression of #20")
        return 1
    print("PASS: rollback stayed inside the listing workspace")
    return 0


def main() -> int:
    code = 1
    with tempfile.TemporaryDirectory() as tmp:
        try:
            code = _run(tmp)
        finally:
            # Windows refuses to delete a directory that is any process's
            # cwd (WinError 32); step out of the sandbox before cleanup.
            # POSIX permits deleting a busy cwd, so this is a no-op there.
            os.chdir(Path(tmp).parent)
    return code


if __name__ == "__main__":
    sys.exit(main())
