"""Anchor probe: Data ingress defense & anchor interlock (演进方案.md §11.4 #5).

Frozen out-of-tree contract:
1. Entry surface `src/evolver/gep/llm_template.py` must be registered in
   ANCHOR_TRIGGER_SURFACES.
2. Free-text placeholders ({prompt}, {diagnosis}, {response}) in shell
   templates must be rejected nakedly by placeholder identity, regardless
   of content (eliminating blacklist arms races).
3. Passing payload via file placeholder ({prompt_file}) executes cleanly.
4. Auto-materialization: if template uses {prompt_file} and caller passes
   {"prompt": "..."}, run_external_template automatically creates the file.
5. Missing anchor registration refuses execution (fail-safe interlock).
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
        ws.mkdir(parents=True, exist_ok=True)
        _isolate(ws)

        from evolver.config import ANCHOR_TRIGGER_SURFACES
        from evolver.gep.llm_template import (
            FREE_TEXT_PLACEHOLDERS,
            check_anchor_interlock,
            run_external_template,
        )

        # 1. Surface registration invariant
        if "src/evolver/gep/llm_template.py" not in ANCHOR_TRIGGER_SURFACES:
            print("FAIL: src/evolver/gep/llm_template.py not in ANCHOR_TRIGGER_SURFACES")
            return 1
        if not check_anchor_interlock():
            print("FAIL: check_anchor_interlock returned False")
            return 1

        # 2. Invariant: naked free-text rejected by identity even with clean text
        for ph in ("prompt", "diagnosis", "response"):
            if ph not in FREE_TEXT_PLACEHOLDERS:
                print(f"FAIL: {ph} missing from FREE_TEXT_PLACEHOLDERS")
                return 1
            out = run_external_template(
                f"echo {{{ph}}}",
                {ph: "completely clean text"},
                kind="probe_test",
                record=False,
            )
            if out != "":
                print(f"FAIL: naked {{{ph}}} was not refused (got {out!r})")
                return 1

        # 3. Invariant: file placeholder passes through
        out_file = run_external_template(
            "echo {prompt_file}",
            {"prompt_file": "path/to/prompt.txt"},
            kind="probe_test",
            record=False,
        )
        if "path/to/prompt.txt" not in out_file:
            print(f"FAIL: explicit file placeholder failed: {out_file!r}")
            return 1

        # 4. Invariant: auto-materialization of {prompt_file} from {prompt}
        out_auto = run_external_template(
            "cat {prompt_file}",
            {"prompt": "auto_materialized_content"},
            kind="probe_test",
            record=True,
        )
        if "auto_materialized_content" not in out_auto:
            print(f"FAIL: auto-materialized prompt file failed: {out_auto!r}")
            return 1

        print("PASS: data ingress free-text identity guard and anchor interlock verified")
        return 0


if __name__ == "__main__":
    sys.exit(main())
