"""Tests for evolver.bench.frozen_gate (charter 外部适应度, round-79).

Covers the enforced acceptance semantics: freeze idempotence, establish /
pass / reject / unmeasured / rekeyed verdicts, last-accepted baseline
persistence, digest binding, and the inactive degradation when no frozen
pack exists. The pack gate is solidify's fitness floor — a drop must
reject, and the scoring rules must be unreadable from inside a cycle.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evolver.bench import frozen_gate
from evolver.bench.builtin_pack import build_pack
from evolver.bench.tasks import materialize


@pytest.fixture
def gate_env(temp_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated EVOLVER_HOME + GEP_ASSETS_DIR: the frozen pack lands outside
    the workspace, the baseline inside the acceptance dir."""
    home = temp_workspace / ".evomap-home"
    gep = temp_workspace / ".evolver" / "gep"
    monkeypatch.setenv("EVOLVER_HOME", str(home))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(gep))
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(temp_workspace))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(temp_workspace))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    return temp_workspace


def _complete_val_tasks(tasks: list[dict[str, Any]]) -> None:
    """Write each val task's self-consistent answer into its sandbox (the
    pack's own contract: expected answers score 1.0 under their grader)."""
    root = frozen_gate.sandbox_root(frozen_gate.frozen_pack_path())
    for task in tasks:
        if task.get("split") != frozen_gate.GATE_SPLIT:
            continue
        sandbox = materialize(task, root)
        grader = task["grader"]
        deliverable = sandbox / str(grader["file"])
        gtype = grader["type"]
        if gtype == "exact":
            deliverable.write_text(str(grader["expected"]), encoding="utf-8")
        elif gtype == "contains":
            deliverable.write_text(f"note {grader['expected']} tail", encoding="utf-8")
        elif gtype == "json_field":
            payload: dict[str, Any] = {}
            node: dict[str, Any] = payload
            parts = str(grader["path"]).split(".")
            for part in parts[:-1]:
                node[part] = {}
                node = node[part]
            node[parts[-1]] = grader["expected"]
            deliverable.write_text(json.dumps(payload), encoding="utf-8")
        elif gtype == "code_stdout":
            deliverable.write_text(f"print({grader['expected']!r})\n", encoding="utf-8")


class TestFreeze:
    def test_absent_pack_gate_inactive(self, gate_env: Path) -> None:
        _ = gate_env
        assert frozen_gate.gate_verdict() is None
        assert frozen_gate.gate_snapshot()["armed"] is False

    def test_freeze_writes_builtin_pack(self, gate_env: Path) -> None:
        report = frozen_gate.freeze_charter_pack()
        assert report["frozen"] is True
        assert report["tasks"] == len(build_pack())
        assert frozen_gate.frozen_pack_path().exists()

    def test_freeze_idempotent_without_force(self, gate_env: Path) -> None:
        first = frozen_gate.freeze_charter_pack()
        second = frozen_gate.freeze_charter_pack()
        assert second["frozen"] is False
        assert second["digest"] == first["digest"]

    def test_force_refreezes_restores_builtin(self, gate_env: Path) -> None:
        frozen_gate.freeze_charter_pack()
        # A human edits the frozen bytes directly (that is the rekey path —
        # the gate binds the baseline to whatever rules they wrote).
        path = frozen_gate.frozen_pack_path()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["tasks"][0]["title"] = "human-edit"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        # --force restores the built-in template (the standard rules), never
        # silently on its own.
        second = frozen_gate.freeze_charter_pack(force=True)
        assert second["frozen"] is True
        restored = json.loads(path.read_text(encoding="utf-8"))
        assert restored["tasks"][0]["title"] != "human-edit"

    def test_invalid_frozen_pack_degrades_to_inactive(self, gate_env: Path) -> None:
        frozen_gate.freeze_charter_pack()
        path = frozen_gate.frozen_pack_path()
        path.write_text('{"tasks": [{"id": "broken"}]}', encoding="utf-8")
        assert frozen_gate.load_frozen_pack() is None
        assert frozen_gate.gate_verdict() is None


class TestGateVerdicts:
    def test_establish_first_armed_run(self, gate_env: Path) -> None:
        frozen_gate.freeze_charter_pack()
        _complete_val_tasks(build_pack())
        verdict = frozen_gate.gate_verdict()
        assert verdict is not None
        assert verdict["verdict"] == "established"
        assert verdict["score"] == 1.0
        assert verdict["baseline"] is None
        persisted = frozen_gate.load_baseline()
        assert persisted is not None and persisted["score"] == 1.0

    def test_flat_and_up_pass_and_advance_baseline(self, gate_env: Path) -> None:
        frozen_gate.freeze_charter_pack()
        tasks = build_pack()
        _complete_val_tasks(tasks)
        # Establish below the ceiling: one val deliverable missing (0.8),
        # then restored — the up-crossing must pass and advance the baseline.
        val_ids = [t["id"] for t in tasks if t["split"] == frozen_gate.GATE_SPLIT]
        root = frozen_gate.sandbox_root(frozen_gate.frozen_pack_path())
        deliverable = root / val_ids[0] / "out.txt"
        deliverable.unlink()
        established = frozen_gate.gate_verdict()
        assert established["verdict"] == "established"
        assert established["score"] == 0.8
        task = next(t for t in tasks if t["id"] == val_ids[0])
        deliverable.write_text(str(task["grader"]["expected"]), encoding="utf-8")
        up = frozen_gate.gate_verdict()
        assert up["verdict"] == "pass"
        assert frozen_gate.load_baseline()["score"] == 1.0
        # Flat (re-graded, same sandboxes) → still a pass.
        assert frozen_gate.gate_verdict()["verdict"] == "pass"

    def test_drop_rejects_and_keeps_baseline(self, gate_env: Path) -> None:
        frozen_gate.freeze_charter_pack()
        tasks = build_pack()
        _complete_val_tasks(tasks)
        assert frozen_gate.gate_verdict()["verdict"] == "established"
        # Break one val deliverable → one task drops to 0 → 0.8 < 1.0.
        val_ids = [t["id"] for t in tasks if t["split"] == frozen_gate.GATE_SPLIT]
        root = frozen_gate.sandbox_root(frozen_gate.frozen_pack_path())
        (root / val_ids[0] / "out.txt").unlink()
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["baseline"] == 1.0
        assert frozen_gate.load_baseline()["score"] == 1.0, "reject must not move the baseline"

    def test_unmeasured_claims_nothing(self, gate_env: Path) -> None:
        frozen_gate.freeze_charter_pack()
        _complete_val_tasks(build_pack())
        assert frozen_gate.gate_verdict()["verdict"] == "established"
        # Sandboxes wiped entirely: nothing graded → no claim, baseline stays.
        import shutil

        shutil.rmtree(frozen_gate.sandbox_root(frozen_gate.frozen_pack_path()))
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "unmeasured"
        assert verdict["score"] is None
        assert frozen_gate.load_baseline()["score"] == 1.0

    def test_refrozen_pack_rekeys_the_baseline(self, gate_env: Path) -> None:
        frozen_gate.freeze_charter_pack()
        _complete_val_tasks(build_pack())
        assert frozen_gate.gate_verdict()["verdict"] == "established"
        path = frozen_gate.frozen_pack_path()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["tasks"][0]["title"] = "rekeyed title"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "rekeyed"
        assert frozen_gate.load_baseline()["pack_digest"] == verdict["digest"]


class TestSnapshot:
    def test_snapshot_shape_when_armed(self, gate_env: Path) -> None:
        frozen_gate.freeze_charter_pack()
        snap = frozen_gate.gate_snapshot()
        assert snap["armed"] is True
        assert snap["val_tasks"] == 5
        assert snap["baseline"] is None
        assert snap["digest"]
        _complete_val_tasks(build_pack())
        frozen_gate.gate_verdict()
        assert frozen_gate.gate_snapshot()["baseline"] == 1.0

    def test_gate_only_uses_val_split(self, gate_env: Path) -> None:
        """A train-task regression must not move the gate — S26.4 holds."""
        frozen_gate.freeze_charter_pack()
        tasks = build_pack()
        _complete_val_tasks(tasks)
        assert frozen_gate.gate_verdict()["verdict"] == "established"
        root = frozen_gate.sandbox_root(frozen_gate.frozen_pack_path())
        train_ids = [t["id"] for t in tasks if t["split"] == "train"]
        assert train_ids, "builtin pack ships train tasks"
        for tid in train_ids:
            sb = root / tid
            if sb.exists():
                for f in sb.iterdir():
                    f.unlink()
        assert frozen_gate.gate_verdict()["verdict"] == "pass"
