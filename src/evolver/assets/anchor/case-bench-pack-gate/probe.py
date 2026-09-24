"""Anchor probe: frozen bench-pack gate semantics (charter round-79).

The pack gate is solidify's external-fitness floor: one frozen bench pack,
scored out-of-tree, becomes an additional acceptance condition. A mutation
that re-opens any of these holes — turning a pack drop into a pass, moving
the baseline on a reject, or re-keying the bar without a pack change —
would let the engine accept its own fitness regressions even if in-repo
tests were weakened alongside it. Frozen invariants:

1. no frozen pack → gate inactive (solidify unchanged), never a crash;
2. first armed run establishes the last-accepted baseline and passes;
3. a score DROP rejects and the baseline is untouched;
4. flat or up passes and advances the baseline;
5. unmeasured candidates (nothing graded) claim nothing;
6. the baseline binds the pack digest — different rules re-key it.

Synthetic two-task pack (exact graders only — fast, no subprocess);
in-process with the engine env isolated. Exit 0 = pass.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


def _pack() -> dict[str, object]:
    task = {
        "id": "gate-val-{n}",
        "split": "val",
        "title": "probe task {n}",
        "prompt": "Write x to out.txt.",
        "sandbox": {"in.txt": "seed\n"},
        "grader": {"type": "exact", "file": "out.txt", "expected": "x"},
    }
    return {
        "pack_version": 1,
        "tasks": [
            {**task, "id": "gate-val-1", "title": "probe task 1"},
            {**task, "id": "gate-val-2", "title": "probe task 2"},
        ],
    }


def _write_pack(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _complete_all(root: Path) -> None:
    for tid in ("gate-val-1", "gate-val-2"):
        sb = root / tid
        sb.mkdir(parents=True, exist_ok=True)
        (sb / "out.txt").write_text("x", encoding="utf-8")


def _check() -> None:
    from evolver.bench import frozen_gate

    # 1. absent pack → inactive
    assert frozen_gate.gate_verdict() is None, "no pack must mean gate inactive"
    assert frozen_gate.gate_snapshot()["armed"] is False

    pack_path = frozen_gate.frozen_pack_path()
    _write_pack(pack_path, _pack())
    root = frozen_gate.sandbox_root(pack_path)

    # 2. establish: everything correct → 1.0, baseline recorded
    _complete_all(root)
    v = frozen_gate.gate_verdict()
    assert v is not None and v["verdict"] == "established" and v["score"] == 1.0, v
    baseline = frozen_gate.load_baseline()
    assert baseline is not None and baseline["score"] == 1.0, baseline

    # 3. drop → reject, baseline untouched
    (root / "gate-val-1" / "out.txt").write_text("wrong", encoding="utf-8")
    v = frozen_gate.gate_verdict()
    assert v["verdict"] == "reject" and v["baseline"] == 1.0, v
    assert frozen_gate.load_baseline()["score"] == 1.0, "reject must not move the baseline"

    # 4. flat/up → pass, baseline advances
    (root / "gate-val-1" / "out.txt").write_text("x", encoding="utf-8")
    v = frozen_gate.gate_verdict()
    assert v["verdict"] == "pass" and v["score"] == 1.0, v
    assert frozen_gate.load_baseline()["score"] == 1.0

    # 5. unmeasured: sandboxes wiped → no claim, baseline stays
    shutil.rmtree(root)
    v = frozen_gate.gate_verdict()
    assert v["verdict"] == "unmeasured" and v["score"] is None, v
    assert frozen_gate.load_baseline()["score"] == 1.0

    # 6. different pack bytes → baseline re-keys (recorded, not hidden)
    payload = _pack()
    payload["tasks"][1]["title"] = "changed rules"  # type: ignore[index]
    _write_pack(pack_path, payload)
    _complete_all(root)
    v = frozen_gate.gate_verdict()
    assert v["verdict"] == "rekeyed", v
    assert frozen_gate.load_baseline()["pack_digest"] == v["digest"]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        (base / "ws").mkdir()
        os.environ.update(
            {
                "EVOLVER_HOME": str(base / "home"),
                "GEP_ASSETS_DIR": str(base / "ws" / ".evolver" / "gep"),
            }
        )
        try:
            _check()
        except AssertionError as exc:
            print(f"FAIL: bench-pack gate invariant violated: {exc}")
            return 1
        print("PASS: pack drop rejects, flat/up passes, baseline binds the frozen rules")
        return 0


if __name__ == "__main__":
    sys.exit(main())
