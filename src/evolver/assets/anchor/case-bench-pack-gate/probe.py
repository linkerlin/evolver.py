"""Anchor probe: frozen bench-pack gate semantics (演进方案.md §5.2).

The pack gate is solidify's external-fitness floor: one frozen bench pack,
scored out-of-tree, becomes an additional acceptance condition. A mutation
that re-opens any of these holes — turning a flat score into a pass, writing
its own result into the bar, or re-keying the bar without a pack change —
would let the engine accept its own fitness regressions even if in-repo
tests were weakened alongside it.

Contract (epoch 13): **only a strict improvement over the last ACCEPTED
score publishes, and a measurement never writes its own result into the
bar.** Before any Accept there is no bar; the Parent bar comes from a
separate, mutation-free measurement (``establish_parent_baseline`` /
``evolver bench baseline``) that solidify cannot reach. Frozen invariants:

1. no frozen pack → reject (there is no "gate inactive" state any more);
2. an armed run with no bar rejects as ``no_baseline`` and writes nothing;
3. the Parent bar is set only by the separate measurement entry point;
4. a flat score rejects and the baseline is untouched;
5. a drop rejects and the baseline is untouched;
6. only ``worst replicate > bar`` accepts — and then advances the baseline;
7. a partial solve is unmeasured, not a partial credit;
8. the baseline binds the pack digest — different rules void it, loudly,
   and nothing rebuilds the bar on its own.

Synthetic two-task pack (exact graders only — fast, no subprocess); both
independent solve slots are graded because a small val split needs two.
In-process with the engine env isolated. Exit 0 = pass.
"""

from __future__ import annotations

import json
import os
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


def _fill(pack_path: Path, wrong: tuple[str, ...] = ()) -> None:
    """Fill BOTH independent solve slots — a small val split needs two."""
    from evolver.bench import frozen_gate

    for index in (1, 2):
        root = frozen_gate.sandbox_root(pack_path, replicate=index)
        for tid in ("gate-val-1", "gate-val-2"):
            sb = root / tid
            sb.mkdir(parents=True, exist_ok=True)
            (sb / "out.txt").write_text("wrong" if tid in wrong else "x", encoding="utf-8")


def _check() -> None:
    from evolver.bench import frozen_gate

    # 1. absent pack → reject, never a silent "gate inactive"
    v = frozen_gate.gate_verdict()
    assert isinstance(v, dict), "gate_verdict must always return a dict"
    assert v["armed"] is False and v["accept"] is False, v
    assert v["verdict"] == "reject" and v["reason"] == "pack_absent", v
    assert frozen_gate.gate_snapshot()["armed"] is False

    pack_path = frozen_gate.frozen_pack_path()
    _write_pack(pack_path, _pack())

    # 2. armed with no bar → reject as no_baseline, and it writes NOTHING.
    #    A candidate that set the bar from its own score would either become
    #    unrepeatable (strong) or let regressions read as improvements (weak).
    _fill(pack_path, wrong=("gate-val-1",))
    v = frozen_gate.gate_verdict()
    assert v["armed"] is True and v["accept"] is False, v
    assert v["verdict"] == "reject" and v["reason"] == "no_baseline", v
    assert frozen_gate.load_baseline() is None, "no Accept yet, so no bar may exist"

    # 3. the Parent bar is written only by the separate, mutation-free entry
    _fill(pack_path, wrong=("gate-val-1", "gate-val-2"))
    parent = frozen_gate.establish_parent_baseline()
    assert parent["ok"] is True and parent["reason"] == "parent_baseline_written", parent
    assert parent["score"] == 0.0, parent
    assert frozen_gate.load_baseline()["score"] == 0.0

    # 4. strict improvement is the ONLY accepting outcome
    _fill(pack_path, wrong=("gate-val-1",))
    v = frozen_gate.gate_verdict()
    assert v["accept"] is True and v["verdict"] == "accept", v
    assert v["reason"] == "strict_improvement" and v["score"] == 0.5, v
    assert frozen_gate.load_baseline()["score"] == 0.5

    # 5. flat → reject, baseline untouched
    v = frozen_gate.gate_verdict()
    assert v["verdict"] == "reject" and v["reason"] == "flat", v
    assert frozen_gate.load_baseline()["score"] == 0.5, "flat must not move the baseline"

    # 6. drop → reject, baseline untouched
    _fill(pack_path, wrong=("gate-val-1", "gate-val-2"))
    v = frozen_gate.gate_verdict()
    assert v["verdict"] == "reject" and v["reason"] == "drop", v
    assert frozen_gate.load_baseline()["score"] == 0.5, "drop must not move the baseline"

    # 7. partial solve → unmeasured, not partial credit. A slot is moved
    #    aside rather than deleted: a frozen contract should not depend on
    #    bulk deletion being permitted in the host it runs in.
    _fill(pack_path, wrong=("gate-val-1",))
    slot = frozen_gate.sandbox_root(pack_path, replicate=2) / "gate-val-1"
    slot.rename(slot.with_name("gate-val-1-set-aside"))
    v = frozen_gate.gate_verdict()
    assert v["verdict"] == "reject" and v["reason"] == "unmeasured", v
    assert v["score"] is None and v["pending_tasks"] == ["gate-val-1"], v
    assert frozen_gate.load_baseline()["score"] == 0.5

    # 8. different pack bytes → the old bar is void, loudly, and NOTHING
    #    rebuilds it (the candidate must not self-re-key)
    payload = _pack()
    payload["tasks"][1]["title"] = "changed rules"  # type: ignore[index]
    _write_pack(pack_path, payload)
    _fill(pack_path, wrong=("gate-val-1",))
    v = frozen_gate.gate_verdict()
    assert v["verdict"] == "reject" and v["reason"] == "rekeyed_void", v
    kept = frozen_gate.load_baseline()
    assert kept is not None and kept["pack_digest"] != v["digest"], (
        "the voided bar must stay on disk bound to the OLD rules, not be rebuilt"
    )
    again = frozen_gate.establish_parent_baseline()
    assert again["ok"] is True and again["baseline"] == 0.5, again


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
        print("PASS: only a strict improvement over an established bar publishes")
        return 0


if __name__ == "__main__":
    sys.exit(main())
