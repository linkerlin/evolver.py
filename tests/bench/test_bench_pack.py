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


# ---------------------------------------------------------------------------
# round-93: the solve prompt carries the named snapshot by id (库即尺子 §5.4)
# ---------------------------------------------------------------------------


def _library_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "memory" / "evolution"))


def test_prompt_without_library_option_has_no_library_section(tmp_path: Path) -> None:
    pack = _write_pack(tmp_path, _two_task_pack())
    plain = pack_prompt(pack, "val-exact-1")
    assert "Library snapshot" not in plain
    assert "read-only design context" not in plain


def test_prompt_with_named_snapshot_pastes_content_by_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _library_env(tmp_path, monkeypatch)
    from evolver.gep import library

    stored = library.save_version(
        {"genes": [{"id": "gene_a", "strategy": ["tie? earlier id wins"]}]}
    )
    snap = str(stored["snapshot"])

    pack = _write_pack(tmp_path, _two_task_pack())
    prompt = pack_prompt(pack, "val-exact-1", library_snapshot=snap)

    assert snap in prompt  # the id, so the run can prove which library it solved with
    assert "tie? earlier id wins" in prompt  # the content, pasted in
    assert "Do NOT open or edit any library store" in prompt  # confinement kept
    # reading by id never moves active
    assert library.active_snapshot_id() is None


def test_prompt_with_unknown_snapshot_id_is_an_error(tmp_path: Path) -> None:
    pack = _write_pack(tmp_path, _two_task_pack())
    with pytest.raises(ValueError, match="not found"):
        pack_prompt(pack, "val-exact-1", library_snapshot="sha256:absent")


# ---------------------------------------------------------------------------
# round-94: solve receipts — provenance for what a solve saw
# ---------------------------------------------------------------------------


def test_prompt_writes_a_solve_receipt(tmp_path: Path) -> None:
    pack = _write_pack(tmp_path, _two_task_pack())
    pack_prompt(pack, "val-exact-1", replicate=1)
    receipt = json.loads(
        (tmp_path / "sandboxes" / "r1" / "_receipts" / "val-exact-1.json").read_text(
            encoding="utf-8"
        )
    )
    assert receipt["format"] == "evolver.solve_receipt.v0"
    assert receipt["task"] == "val-exact-1"
    assert receipt["replicate"] == 1
    assert receipt["library"] is None
    assert len(receipt["pack_digest"]) == 16
    assert receipt["written_at"].endswith("Z")


def test_prompt_receipt_names_the_injected_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _library_env(tmp_path, monkeypatch)
    from evolver.gep import library

    snap = str(library.save_version({"genes": []})["snapshot"])
    pack = _write_pack(tmp_path, _two_task_pack())
    pack_prompt(pack, "val-exact-1", library_snapshot=snap)
    receipt = json.loads(
        (tmp_path / "sandboxes" / "_receipts" / "val-exact-1.json").read_text(encoding="utf-8")
    )
    assert receipt["library"] == snap


def test_prompt_receipt_cost_fields_start_unmeasured(tmp_path: Path) -> None:
    """§5.7 采集先行: cost/model 起手 null (unmeasured), 不猜不零填.

    receipt 在求解前写 (记的是求解看到的东西), token 与模型配置只在观测到
    之后由 record_cost 回填——起手必须是 null, 而不是 0 或空串。"""
    pack = _write_pack(tmp_path, _two_task_pack())
    pack_prompt(pack, "val-exact-1", replicate=1)
    receipt = json.loads(
        (tmp_path / "sandboxes" / "r1" / "_receipts" / "val-exact-1.json").read_text(
            encoding="utf-8"
        )
    )
    assert "cost" in receipt and receipt["cost"] is None
    assert "model" in receipt and receipt["model"] is None


def test_prompt_failure_writes_no_receipt(tmp_path: Path) -> None:
    pack = _write_pack(tmp_path, _two_task_pack())
    with pytest.raises(ValueError):
        pack_prompt(pack, "val-exact-1", library_snapshot="sha256:absent")
    assert not (tmp_path / "sandboxes" / "_receipts").exists()
