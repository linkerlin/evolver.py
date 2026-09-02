"""S26.1c pack executor: prompt → (external agent) → grade → aggregate → ledger.

The engine never runs an agent: `pack_prompt` prints, `grade` scores, and
`run_pack` aggregates a split into one R measurement (S26.4: gate on val).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evolver.bench.runner import (
    grade_pack_task,
    load_pack,
    pack_prompt,
    run_pack,
)


def _write_pack(tmp_path: Path, tasks: list[dict[str, Any]]) -> Path:
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps(tasks), encoding="utf-8")
    return path


def _two_task_pack() -> list[dict[str, Any]]:
    return [
        {
            "id": "train-exact-1",
            "split": "train",
            "title": "Echo spec",
            "prompt": "Write 'alpha' to out.txt",
            "sandbox": {"spec.txt": "alpha"},
            "grader": {"type": "exact", "file": "out.txt", "expected": "alpha"},
        },
        {
            "id": "val-exact-1",
            "split": "val",
            "title": "Echo spec",
            "prompt": "Write 'beta' to out.txt",
            "sandbox": {"spec.txt": "beta"},
            "grader": {"type": "exact", "file": "out.txt", "expected": "beta"},
        },
    ]


def test_prompt_materializes_and_embeds_workdir(tmp_path: Path) -> None:
    pack = _write_pack(tmp_path, _two_task_pack())
    prompt = pack_prompt(pack, "val-exact-1")
    sandbox = tmp_path / "sandboxes" / "val-exact-1"
    assert f"WORKING DIRECTORY: {sandbox.resolve()}" in prompt
    assert "beta" in prompt  # task prompt content present
    assert (sandbox / "spec.txt").exists()


def test_prompt_rejects_unknown_task(tmp_path: Path) -> None:
    pack = _write_pack(tmp_path, _two_task_pack())
    with pytest.raises(ValueError, match="not in pack"):
        pack_prompt(pack, "nope")


def test_grade_before_agent_run_is_pending_error(tmp_path: Path) -> None:
    pack = _write_pack(tmp_path, _two_task_pack())
    with pytest.raises(ValueError, match="sandbox missing"):
        grade_pack_task(pack, "val-exact-1")


def test_full_semiauto_roundtrip(tmp_path: Path) -> None:
    """prompt → simulate an external agent writing the deliverable → grade."""
    pack = _write_pack(tmp_path, _two_task_pack())
    prompt = pack_prompt(pack, "val-exact-1")
    assert "WORKING DIRECTORY" in prompt
    # --- the external agent's turn ---
    deliverable = tmp_path / "sandboxes" / "val-exact-1" / "out.txt"
    deliverable.write_text("beta", encoding="utf-8")
    # --- back to the engine ---
    assert grade_pack_task(pack, "val-exact-1") == 1.0


def test_run_pack_gates_only_val_split(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """S26.4 discipline: --split val excludes train tasks from the gate R."""
    evo = tmp_path / "evo"
    evo.mkdir(parents=True)
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    pack_path = _write_pack(tmp_path, _two_task_pack())
    pack_prompt(pack_path, "train-exact-1")
    pack_prompt(pack_path, "val-exact-1")
    # Agent got the train task right, the val task wrong.
    (tmp_path / "sandboxes" / "train-exact-1" / "out.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "sandboxes" / "val-exact-1" / "out.txt").write_text("WRONG", encoding="utf-8")

    val = run_pack(pack_path, split="val")
    assert val["score"] == 0.0  # only the val task counted
    assert [r["id"] for r in val["per_task"]] == ["val-exact-1"]
    from evolver.gep.fitness_state import load_domain

    assert load_domain("bench:pack:val")["r_best"] == 0.0

    train = run_pack(pack_path, split="train", record=False)
    assert train["score"] == 1.0


def test_run_pack_pending_tasks_excluded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    evo = tmp_path / "evo"
    evo.mkdir(parents=True)
    monkeypatch.setenv("EVOLUTION_DIR", str(evo))
    monkeypatch.setenv("EVOLVER_REPO_ROOT", str(tmp_path))
    pack_path = _write_pack(tmp_path, _two_task_pack())
    # Only the train sandbox materialized; val never prompted.
    pack_prompt(pack_path, "train-exact-1")
    (tmp_path / "sandboxes" / "train-exact-1" / "out.txt").write_text("alpha", encoding="utf-8")
    result = run_pack(pack_path, split="val")
    assert result["score"] is None  # nothing graded → nothing claimed
    assert result["verdict"] is None  # unmeasured never touches the ledger
    assert result["per_task"][0]["status"] == "pending"


def test_load_pack_rejects_invalid(tmp_path: Path) -> None:
    bad = _write_pack(tmp_path, [{"id": "x"}])
    with pytest.raises(ValueError, match="invalid task pack"):
        load_pack(bad)
