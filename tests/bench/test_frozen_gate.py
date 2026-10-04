"""Tests for evolver.bench.frozen_gate (charter 配对会话 §5.2).

Supersedes round-79 semantics: the gate no longer asks "did the score drop?"
but "is this strictly better than the Parent?" Drop, flat, unmeasured, a
damaged gate, an absent pack and a voided baseline all reject, and a reject
never moves the baseline. Small val splits additionally need two independent
solves, both better than the bar.

Freeze idempotence, digest binding and baseline persistence still hold.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evolver.bench import frozen_gate
from evolver.bench.builtin_pack import build_pack
from evolver.bench.tasks import materialize
from evolver.gep.anchor import anchor_dir


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


def _complete_val_tasks(
    tasks: list[dict[str, Any]],
    *,
    replicates: tuple[int, ...] = (1, 2),
) -> None:
    """Write each val task's self-consistent answer into every solve slot (the
    pack's own contract: expected answers score 1.0 under their grader).

    §5.2 asks the host to solve val independently twice, so the default fills
    both r1 and r2.
    """
    for replicate in replicates:
        root = frozen_gate.sandbox_root(frozen_gate.frozen_pack_path(), replicate=replicate)
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
    def test_absent_pack_rejects(self, gate_env: Path) -> None:
        """No exam, no score, no publish — §5.2 retired the "gate inactive"
        escape hatch (round-79 let the mutation through here)."""
        _ = gate_env
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "pack_absent"
        assert verdict["accept"] is False
        assert frozen_gate.gate_snapshot()["armed"] is False
        assert frozen_gate.gate_snapshot()["train_ids"] == []

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

    def test_invalid_frozen_pack_rejects(self, gate_env: Path) -> None:
        frozen_gate.freeze_charter_pack()
        path = frozen_gate.frozen_pack_path()
        path.write_text('{"tasks": [{"id": "broken"}]}', encoding="utf-8")
        assert frozen_gate.load_frozen_pack() is None
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "pack_absent"


class TestGateVerdicts:
    def test_armed_run_without_a_baseline_rejects_and_writes_nothing(self, gate_env: Path) -> None:
        """Before any Accept there is no bar, and a measurement must never
        write its own result into it.

        Letting the first candidate set the bar has two death traps: a strong
        one raises the bar to itself and the same improvement can never be
        accepted again; a weak one sinks the bar below Parent so a regression
        reads as "strictly better". The Parent bar comes from the separate,
        mutation-free measurement instead.
        """
        frozen_gate.freeze_charter_pack()
        _complete_val_tasks(build_pack())
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "no_baseline"
        assert verdict["accept"] is False
        assert verdict["score"] == 1.0
        assert frozen_gate.load_baseline() is None, "no Accept yet, so no bar may exist"

    def test_parent_baseline_is_written_only_by_the_separate_entry(self, gate_env: Path) -> None:
        frozen_gate.freeze_charter_pack()
        _complete_val_tasks(build_pack())
        report = frozen_gate.establish_parent_baseline()
        assert report["ok"] is True and report["reason"] == "parent_baseline_written"
        assert report["score"] == 1.0
        assert frozen_gate.load_baseline()["score"] == 1.0

    def test_improvement_accepts_and_advances_baseline(self, gate_env: Path) -> None:
        frozen_gate.freeze_charter_pack()
        tasks = build_pack()
        val_ids = [t["id"] for t in tasks if t["split"] == frozen_gate.GATE_SPLIT]
        # A Parent bar below the ceiling: one val deliverable WRONG in both
        # slots (0.8). Missing would be pending — and a partial solve is not a
        # measurement any more.
        for replicate in (1, 2):
            root = frozen_gate.sandbox_root(frozen_gate.frozen_pack_path(), replicate=replicate)
            _complete_val_tasks(tasks, replicates=(replicate,))
            (root / val_ids[0] / "out.txt").write_text("wrong", encoding="utf-8")
        established = frozen_gate.establish_parent_baseline()
        assert established["ok"] is True and established["score"] == 0.8, established

        task = next(t for t in tasks if t["id"] == val_ids[0])
        for replicate in (1, 2):
            root = frozen_gate.sandbox_root(frozen_gate.frozen_pack_path(), replicate=replicate)
            (root / val_ids[0] / "out.txt").write_text(
                str(task["grader"]["expected"]), encoding="utf-8"
            )
        up = frozen_gate.gate_verdict()
        assert up["verdict"] == "accept"
        assert up["reason"] == "strict_improvement"
        assert frozen_gate.load_baseline()["score"] == 1.0

    def test_flat_rejects_and_keeps_baseline(self, gate_env: Path) -> None:
        """round-79 passed a flat score. Equal to the Parent is not better."""
        frozen_gate.freeze_charter_pack()
        tasks = build_pack()
        _complete_val_tasks(tasks)
        frozen_gate.establish_parent_baseline()
        flat = frozen_gate.gate_verdict()
        assert flat["verdict"] == "reject"
        assert flat["reason"] == "flat"
        assert flat["score"] == 1.0
        assert frozen_gate.load_baseline()["score"] == 1.0

    def test_drop_rejects_and_keeps_baseline(self, gate_env: Path) -> None:
        frozen_gate.freeze_charter_pack()
        tasks = build_pack()
        _complete_val_tasks(tasks)
        frozen_gate.establish_parent_baseline()
        # Break one val deliverable in both slots → one task drops to 0.
        val_ids = [t["id"] for t in tasks if t["split"] == frozen_gate.GATE_SPLIT]
        for replicate in (1, 2):
            root = frozen_gate.sandbox_root(frozen_gate.frozen_pack_path(), replicate=replicate)
            (root / val_ids[0] / "out.txt").write_text("wrong", encoding="utf-8")
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "drop"
        assert verdict["baseline"] == 1.0
        assert frozen_gate.load_baseline()["score"] == 1.0, "reject must not move the baseline"

    def test_partial_solve_is_unmeasured_not_partial_credit(self, gate_env: Path) -> None:
        """One pending val task makes the whole replicate unmeasured — a
        single lucky task above the bar is not a measurement."""
        frozen_gate.freeze_charter_pack()
        tasks = build_pack()
        _complete_val_tasks(tasks)
        frozen_gate.establish_parent_baseline()
        val_ids = [t["id"] for t in tasks if t["split"] == frozen_gate.GATE_SPLIT]
        # Slot r2 leaves one val task unsolved; r1 is perfect.
        perfect = frozen_gate.sandbox_root(frozen_gate.frozen_pack_path(), replicate=1)
        _complete_val_tasks(tasks, replicates=(1,))
        _ = perfect
        partial = frozen_gate.sandbox_root(frozen_gate.frozen_pack_path(), replicate=2)
        (partial / val_ids[1]).rename(partial / (val_ids[1] + "-set-aside"))
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "unmeasured"
        assert verdict["score"] is None
        assert verdict["pending_tasks"] == [val_ids[1]]
        assert frozen_gate.load_baseline()["score"] == 1.0

    def test_unmeasured_rejects(self, gate_env: Path) -> None:
        """An unsolved val split proves nothing — it is not a free pass."""
        frozen_gate.freeze_charter_pack()
        _complete_val_tasks(build_pack())
        frozen_gate.establish_parent_baseline()
        import shutil

        for replicate in (1, 2):
            shutil.rmtree(
                frozen_gate.sandbox_root(frozen_gate.frozen_pack_path(), replicate=replicate)
            )
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "unmeasured"
        assert verdict["score"] is None
        assert frozen_gate.load_baseline()["score"] == 1.0

    def test_refrozen_pack_voids_the_bar_and_rebuilds_nothing(self, gate_env: Path) -> None:
        frozen_gate.freeze_charter_pack()
        _complete_val_tasks(build_pack())
        frozen_gate.establish_parent_baseline()
        old_digest = frozen_gate.load_baseline()["pack_digest"]
        path = frozen_gate.frozen_pack_path()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["tasks"][0]["title"] = "rekeyed title"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        verdict = frozen_gate.gate_verdict()
        # The rules changed: the old bar is void — and the candidate must not
        # re-key it to its own score. The voided bar stays on disk, bound to
        # the OLD rules, until a fresh Parent measurement replaces it.
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "rekeyed_void"
        kept = frozen_gate.load_baseline()
        assert kept["pack_digest"] == old_digest
        assert kept["pack_digest"] != verdict["digest"]


def _write_big_pack(val_n: int = 12, train_n: int = 2) -> list[dict[str, Any]]:
    """Install a human-authored BIG pack (> REPLICATE_VAL_MAX val tasks) at
    the frozen path. This is the charter's "the human swaps the pack" move —
    the gate keys its decision rule on the pack the human froze."""
    tasks: list[dict[str, Any]] = []
    for i in range(val_n):
        tasks.append(
            {
                "id": f"big-val-{i}",
                "split": "val",
                "title": f"Echo token {i}",
                "prompt": f"Write the token '{i}' to out.txt.",
                "sandbox": {"in.txt": "echo\n"},
                "grader": {"type": "exact", "file": "out.txt", "expected": str(i)},
            }
        )
    for i in range(train_n):
        tasks.append(
            {
                "id": f"big-train-{i}",
                "split": "train",
                "title": f"Echo train token {i}",
                "prompt": f"Write the token 't{i}' to out.txt.",
                "sandbox": {"in.txt": "echo\n"},
                "grader": {"type": "exact", "file": "out.txt", "expected": f"t{i}"},
            }
        )
    path = frozen_gate.frozen_pack_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pack_version": 1, "tasks": tasks}), encoding="utf-8")
    return tasks


def _solve_big(
    tasks: list[dict[str, Any]],
    *,
    fail: set[str],
) -> None:
    """Solve every val task into the SINGLE flat slot a big pack uses
    (replicates=1 — the paired rule does not multiply solve slots)."""
    root = frozen_gate.sandbox_root(frozen_gate.frozen_pack_path(), replicate=None)
    for task in tasks:
        if task.get("split") != frozen_gate.GATE_SPLIT:
            continue
        sandbox = materialize(task, root)
        deliverable = sandbox / str(task["grader"]["file"])
        deliverable.write_text(
            "wrong" if task["id"] in fail else str(task["grader"]["expected"]),
            encoding="utf-8",
        )


class TestBigPackPairedCompare:
    """val > REPLICATE_VAL_MAX: publication moves to bench/compare.py
    (exact two-sided binomial on discordant pairs, alpha = 0.05, discordant
    >= 8). The 5-task pack keeps the two-replicates-strictly-above rule."""

    def test_a_paired_win_publishes_and_moves_the_bar(self, gate_env: Path) -> None:
        tasks = _write_big_pack()
        # Parent: fails big-val-0..9, passes big-val-10/11 (all GRADED —
        # a wrong answer is a measurement, a missing one is not).
        _solve_big(tasks, fail={f"big-val-{i}" for i in range(10)})
        established = frozen_gate.establish_parent_baseline()
        assert established["ok"] is True, established
        assert established["replicates"] == 1

        # Candidate: fixes big-val-0..8, still fails big-val-9. Ten wins...
        # no — nine wins, zero losses, discordant 9 >= 8, p = 2/2^9.
        _solve_big(tasks, fail={"big-val-9"})
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "accept", verdict
        assert verdict["reason"] == "paired_improvement"
        assert verdict["verdict_mode"] == "paired_compare"
        assert verdict["compare"][0]["discordant"] == 9
        assert verdict["compare"][0]["p"] <= 0.05
        assert frozen_gate.load_baseline()["score"] == round(11 / 12, 4)

    def test_not_enough_discordant_rejects_and_keeps_the_bar(self, gate_env: Path) -> None:
        tasks = _write_big_pack()
        _solve_big(tasks, fail={f"big-val-{i}" for i in range(10)})
        assert frozen_gate.establish_parent_baseline()["ok"] is True

        # Candidate fixes only five of the ten: direction is right, but five
        # discordant pairs cannot carry a decision.
        _solve_big(tasks, fail={f"big-val-{i}" for i in range(5, 10)})
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "not_enough_discordant"
        assert verdict["discordant"] == 5
        assert frozen_gate.load_baseline()["score"] == round(2 / 12, 4)

    def test_a_paired_regression_rejects_as_parent_better(self, gate_env: Path) -> None:
        """The paired test is the big pack's no-regression guard: a candidate
        that breaks nine working tasks to fix one shows the wrong direction
        at significance, and the gate refuses."""
        tasks = _write_big_pack()
        _solve_big(tasks, fail={"big-val-0"})  # Parent passes 11 of 12.
        assert frozen_gate.establish_parent_baseline()["ok"] is True

        # Candidate fixes big-val-0 but collapses big-val-2..10 (nine lost
        # pairs): wins 1 vs 9, p ≈ 0.0215 -> parent_better.
        _solve_big(tasks, fail={f"big-val-{i}" for i in range(2, 11)})
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "parent_better"
        assert verdict["compare"][0]["verdict"] == "b_better"
        assert frozen_gate.load_baseline()["score"] == round(11 / 12, 4)

    def test_no_significant_difference_rejects(self, gate_env: Path) -> None:
        tasks = _write_big_pack()
        _solve_big(tasks, fail={f"big-val-{i}" for i in range(6)})
        assert frozen_gate.establish_parent_baseline()["ok"] is True

        # Candidate trades even-ish: fixes all six of the Parent's fails,
        # breaks four of the Parent's passes. wins 6 vs 4, discordant 10 ->
        # p ≈ 0.75 -> honestly reported as no signal (and the evidence
        # floor is met, so the reason is the comparison's, not the count's).
        _solve_big(tasks, fail={"big-val-6", "big-val-7", "big-val-8", "big-val-9"})
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "no_significant_difference"
        assert verdict["compare"][0]["verdict"] == "no_significant_difference"
        assert verdict["compare"][0]["discordant"] == 10
        assert frozen_gate.load_baseline()["score"] == 0.5

    def test_a_baseline_without_pairs_rejects(self, gate_env: Path) -> None:
        """A bar with no per-task record cannot be paired against — an
        unpairable bar is a refusal, never a waiver."""
        tasks = _write_big_pack()
        _solve_big(tasks, fail=set())
        digest = frozen_gate.pack_digest(frozen_gate.frozen_pack_path())
        frozen_gate.save_baseline(0.5, digest)  # no per_task
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "baseline_without_per_task"
        assert frozen_gate.load_baseline()["score"] == 0.5

    def test_task_set_mismatch_rejects(self, gate_env: Path) -> None:
        """A baseline measured on another task set cannot pair — the
        comparison would be meaningless, so it refuses instead of crashing."""
        tasks = _write_big_pack()
        _solve_big(tasks, fail=set())
        digest = frozen_gate.pack_digest(frozen_gate.frozen_pack_path())
        frozen_gate.save_baseline(0.5, digest, per_task={"alien-task": 1.0})
        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "task_set_mismatch"

    def test_val_ids_stay_sealed_in_declarations_on_a_big_pack(self, gate_env: Path) -> None:
        """The declaration split check does not loosen because the pack grew:
        a candidate still may not cite val ids it must not know."""
        tasks = _write_big_pack()
        _solve_big(tasks, fail={f"big-val-{i}" for i in range(10)})
        assert frozen_gate.establish_parent_baseline()["ok"] is True
        _solve_big(tasks, fail={"big-val-9"})
        verdict = frozen_gate.gate_verdict(
            declaration={"no_regressions": [{"id": "big-val-0", "floor": 0.9}]}
        )
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "bad_regression_declaration"
        assert frozen_gate.load_baseline()["score"] == round(2 / 12, 4)

    def test_the_candidate_declaration_binds_on_a_big_pack(
        self, gate_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With the split list unavailable the declaration is still asserted
        against the graded rounds — a promised floor is checked, and a
        broken one rejects before the comparison even runs."""
        tasks = _write_big_pack()
        _solve_big(tasks, fail={f"big-val-{i}" for i in range(10)})
        assert frozen_gate.establish_parent_baseline()["ok"] is True
        monkeypatch.setattr(frozen_gate, "_gate_task_ids", lambda: None)

        # A floor the candidate breaks: big-val-9 scores 0.0 < 0.9. The
        # declaration rejects before the comparison, and the bar stays put.
        _solve_big(tasks, fail={"big-val-9"})
        verdict = frozen_gate.gate_verdict(
            declaration={"no_regressions": [{"id": "big-val-9", "floor": 0.9}]}
        )
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "regression_below_floor"
        assert frozen_gate.load_baseline()["score"] == round(2 / 12, 4)

        # A floor the candidate keeps: big-val-0 scores 1.0 >= 0.9 — the
        # declaration holds and the paired win publishes.
        verdict = frozen_gate.gate_verdict(
            declaration={"no_regressions": [{"id": "big-val-0", "floor": 0.9}]}
        )
        assert verdict["verdict"] == "accept", verdict
        assert frozen_gate.load_baseline()["score"] == round(11 / 12, 4)


class TestSnapshot:
    def test_snapshot_shape_when_armed(self, gate_env: Path) -> None:
        frozen_gate.freeze_charter_pack()
        snap = frozen_gate.gate_snapshot()
        assert snap["armed"] is True
        assert snap["val_tasks"] == 5
        assert snap["baseline"] is None
        val_ids = {t["id"] for t in build_pack() if t["split"] == "val"}
        assert snap["train_ids"]
        assert not set(snap["train_ids"]) & val_ids
        assert snap["digest"]
        _complete_val_tasks(build_pack())
        frozen_gate.establish_parent_baseline()
        assert frozen_gate.gate_snapshot()["baseline"] == 1.0

    def test_gate_only_uses_val_split(self, gate_env: Path) -> None:
        """A train-task regression must not move the gate — S26.4 holds."""
        frozen_gate.freeze_charter_pack()
        tasks = build_pack()
        _complete_val_tasks(tasks)
        frozen_gate.establish_parent_baseline()
        train_ids = [t["id"] for t in tasks if t["split"] == "train"]
        assert train_ids, "builtin pack ships train tasks"
        for replicate in (1, 2):
            root = frozen_gate.sandbox_root(frozen_gate.frozen_pack_path(), replicate=replicate)
            for tid in train_ids:
                sb = root / tid
                if sb.exists():
                    for f in sb.iterdir():
                        f.unlink()
        assert frozen_gate.gate_verdict()["verdict"] == "reject"

    def test_a_collapsed_task_rejects_even_when_the_mean_rises(self, gate_env: Path) -> None:
        """The mean is not the whole measurement.

        A candidate can raise the average while collapsing one task: the
        aggregate gate sees only the sum, so it would publish a pack that
        silently lost a capability. The Parent's per-task scores are floors,
        and falling under one is a regression.
        """
        frozen_gate.freeze_charter_pack()
        tasks = build_pack()
        val_ids = [t["id"] for t in tasks if t["split"] == frozen_gate.GATE_SPLIT]
        assert len(val_ids) >= 3, "needs three val tasks to trade one off"

        def _solve(wrong: list[str]) -> None:
            """Solve every val task correctly, then break the named ones."""
            for replicate in (1, 2):
                root = frozen_gate.sandbox_root(frozen_gate.frozen_pack_path(), replicate=replicate)
                _complete_val_tasks(tasks, replicates=(replicate,))
                for tid in wrong:
                    task = next(t for t in tasks if t["id"] == tid)
                    deliverable = root / tid / str(task["grader"]["file"])
                    deliverable.write_text("wrong", encoding="utf-8")

        # Parent: two val tasks wrong -> 0.6, the rest sitting at 1.0.
        _solve(val_ids[1:3])
        established = frozen_gate.establish_parent_baseline()
        assert established["ok"] is True and established["score"] == 0.6, established

        # Candidate: those two fixed, but a DIFFERENT task collapses. The mean
        # rises 0.6 -> 0.8 while a floor of 1.0 falls to 0.0.
        _solve([val_ids[0]])
        verdict = frozen_gate.gate_verdict()
        assert verdict["score"] == 0.8, verdict
        assert verdict["accept"] is False
        assert verdict["reason"] == "regression_below_floor"
        # A regression is a reject, and a reject never moves the bar.
        assert frozen_gate.load_baseline()["score"] == 0.6

    def test_a_reseeded_anchor_voids_the_bar(self, gate_env: Path) -> None:
        """The acceptance protocol is frozen together with the bar.

        Re-seeding the anchor suite (``anchor init --epoch N``) does not
        change the frozen pack's bytes, so the digest still matches — but the
        contracts judging the candidate are new. An old bar must not judge
        under a new ruler.
        """
        frozen_gate.freeze_charter_pack()
        _complete_val_tasks(build_pack())
        assert frozen_gate.establish_parent_baseline()["ok"] is True

        epoch_path = anchor_dir() / "epoch.json"
        epoch_path.parent.mkdir(parents=True, exist_ok=True)
        epoch_path.write_text(json.dumps({"epoch": 99, "cases": []}), encoding="utf-8")

        verdict = frozen_gate.gate_verdict()
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "protocol_drift"
        assert verdict["baseline_epoch"] is None
        assert verdict["anchor_epoch"] == 99
