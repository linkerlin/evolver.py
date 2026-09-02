"""Built-in deterministic pack (S26.1 completion): generation + self-consistency."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.bench.builtin_pack import (
    build_pack,
    load_builtin_tasks,
    write_pack,
)
from evolver.bench.runner import load_pack
from evolver.bench.scoring import grade
from evolver.bench.tasks import materialize, validate_tasks


def test_pack_is_deterministic(tmp_path: Path) -> None:
    """Two invocations are byte-identical — no randomness, no wall-clock."""
    a = write_pack(tmp_path / "a" / "tasks.json")
    b = write_pack(tmp_path / "b" / "tasks.json")
    assert a.read_bytes() == b.read_bytes()


def test_pack_shape() -> None:
    tasks = build_pack()
    assert len(tasks) == 12
    assert validate_tasks(tasks) == []
    splits = {t["split"] for t in tasks}
    assert splits == {"train", "val"}
    val = [t for t in tasks if t["split"] == "val"]
    assert len(val) >= 4  # a real held-out surface, not a token one
    grader_types = {t["grader"]["type"] for t in tasks}
    assert grader_types == {"exact", "contains", "json_field", "code_stdout"}


def test_trap_clauses_actually_trap() -> None:
    """The double-exclusion trap must differ from its single-clause shadow —
    asserted at generation time (bugs must not compensate)."""
    trap = next(t for t in build_pack() if t["id"] == "trap-double-exclusion-val")
    expected = trap["grader"]["expected"].split("\n")
    names = trap["sandbox"]["names.txt"].split("\n")
    only_clause_a = [n for n in names if "e" not in n]
    assert expected != only_clause_a  # clause B bites
    assert expected != names  # clause A bites


def test_self_consistency_all_four_graders(tmp_path: Path) -> None:
    """Review-erratum fix: EVERY task's expected answer, written back into
    its sandbox, scores 1.0 under its own grader — all four grader types."""
    tasks = build_pack()
    seen_types: set[str] = set()
    for task in tasks:
        sandbox = materialize(task, tmp_path / "sandboxes")
        gtype = task["grader"]["type"]
        if gtype == "code_stdout":
            # the "expected answer" for code tasks is the script that prints it
            (sandbox / task["grader"]["script"]).write_text(
                f"print({task['grader']['expected']!r})\n", encoding="utf-8"
            )
        elif gtype == "json_field":
            (sandbox / task["grader"]["file"]).write_text(
                json.dumps({"result": task["grader"]["expected"]}), encoding="utf-8"
            )
        else:
            (sandbox / task["grader"]["file"]).write_text(
                task["grader"]["expected"], encoding="utf-8"
            )
        assert grade(task, sandbox) == 1.0, f"{task['id']} ({gtype}) failed self-consistency"
        seen_types.add(gtype)
    assert seen_types == {"exact", "contains", "json_field", "code_stdout"}


def test_wrapped_pack_loads_through_runner(tmp_path: Path) -> None:
    """The {pack_version, tasks} wrapper written by bench init round-trips
    through the same runner path as bare wikiskill lists."""
    path = write_pack(tmp_path / "tasks.json")
    loaded = load_pack(path)
    assert len(loaded) == 12
    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps(loaded), encoding="utf-8")
    assert load_pack(bare) == loaded
    with pytest.raises(ValueError):
        load_builtin_tasks({"unexpected": 1})
    with pytest.raises(ValueError):
        load_builtin_tasks(42)  # type: ignore[arg-type]


def test_bench_init_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from evolver.cli import main

    monkeypatch.chdir(tmp_path)
    assert main(["bench", "init"]) == 0
    out = capsys.readouterr().out
    assert "12 tasks" in out
    data = json.loads((tmp_path / "tasks.json").read_text(encoding="utf-8"))
    assert data["pack_version"] == 1
    assert len(data["tasks"]) == 12
