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

        from evolver.gep.hypothesis import record_hypothesis
        from evolver.gep.solidify import solidify, write_state_for_solidify

        # §5.3 — the gate refuses a Candidate with no declared hypothesis.
        # The probe plays the host's part before the first fold; the duplicate
        # refusal under test rides on already_solidified, not on the
        # hypothesis gate, and must be reachable without re-declaring.
        record_hypothesis(
            {
                "hypothesis": "the repair gene resolves the collected error signal",
                "dimension": "content",
                "mechanism_family": "anchor-fixture",
                "target_hook": "gep.solidify",
                "mechanism_check": [
                    {
                        "id": "gate-train-1",
                        "before": "error signal collected with no candidate response",
                        "after": "candidate folded into the session ledger",
                    }
                ],
            }
        )

        # §5.2 — with the external-fitness charter there is no "gate inactive"
        # any more: an unfrozen pack rejects as pack_absent. Arm the smallest
        # instrument the duplicate check needs: a two-task val pack, a
        # mutation-free Parent bar at 0.0, both solve slots solved.
        from evolver.bench import frozen_gate

        task = {
            "id": "gate-val-{n}",
            "split": "val",
            "title": "probe task {n}",
            "prompt": "Write x to out.txt.",
            "sandbox": {"in.txt": "seed\n"},
            "grader": {"type": "exact", "file": "out.txt", "expected": "x"},
        }
        train = {
            "id": "gate-train-1",
            "split": "train",
            "title": "probe train task",
            "prompt": "Write x to out.txt.",
            "sandbox": {"in.txt": "seed\n"},
            "grader": {"type": "exact", "file": "out.txt", "expected": "x"},
        }
        pack_path = frozen_gate.frozen_pack_path()
        pack_path.parent.mkdir(parents=True, exist_ok=True)
        pack_path.write_text(
            json.dumps(
                {
                    "pack_version": 1,
                    "tasks": [
                        {**task, "id": "gate-val-1", "title": "probe task 1"},
                        {**task, "id": "gate-val-2", "title": "probe task 2"},
                        train,
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        def _fill(wrong_all: bool) -> None:
            for index in (1, 2):
                root = frozen_gate.sandbox_root(pack_path, replicate=index)
                for tid in ("gate-val-1", "gate-val-2"):
                    slot = root / tid
                    slot.mkdir(parents=True, exist_ok=True)
                    (slot / "out.txt").write_text("wrong" if wrong_all else "x", encoding="utf-8")

        _fill(True)
        parent = frozen_gate.establish_parent_baseline()
        if not parent.get("ok"):
            print(f"FAIL: parent baseline not written: {json.dumps(parent)[:300]}")
            return 1
        _fill(False)

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
