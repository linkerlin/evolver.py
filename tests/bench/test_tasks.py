"""Pack schema validation + sandbox materialization (S26.1).

1:1 with ``evolver.bench.tasks``. validate_tasks is the gate a hand-authored
pack passes before placement (round-89 procedure); materialize's force=True
is the phantom-scoring defense — stale artifacts must never be graded.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from evolver.bench.tasks import materialize, validate_tasks


def _valid() -> list[dict[str, Any]]:
    return [
        {
            "id": "spec-a",
            "split": "train",
            "title": "t",
            "prompt": "p",
            "sandbox": {"in.txt": "seed"},
            "grader": {"type": "exact", "file": "out.txt", "expected": "x"},
        }
    ]


class TestValidateTasks:
    def test_a_valid_task_produces_no_errors(self) -> None:
        assert validate_tasks(_valid()) == []

    def test_non_list_input_is_rejected(self) -> None:
        assert validate_tasks("nope") == ["tasks must be a JSON list"]  # type: ignore[arg-type]

    def test_non_object_task_is_rejected(self) -> None:
        errors = validate_tasks(["nope"])  # type: ignore[list-item]
        assert any("not an object" in e for e in errors)

    def test_ids_must_be_lowercase_slugs(self) -> None:
        # digits-first IS legal (^[a-z0-9][a-z0-9-]*$); the rest are not
        for bad in ("UPPER", "with space", "under_score", "", "-lead", "dot.id"):
            errors = validate_tasks([dict(_valid()[0], id=bad)])
            assert any("slug" in e for e in errors), bad

    def test_duplicate_ids_are_rejected(self) -> None:
        tasks = [*_valid(), dict(_valid()[0])]
        assert any("duplicate id" in e for e in validate_tasks(tasks))

    def test_split_must_be_train_or_val(self) -> None:
        errors = validate_tasks([dict(_valid()[0], split="test")])
        assert any("split" in e for e in errors)

    def test_prompt_must_be_nonempty(self) -> None:
        errors = validate_tasks([dict(_valid()[0], prompt="")])
        assert any("prompt" in e for e in errors)

    def test_sandbox_must_be_nonempty_object(self) -> None:
        errors = validate_tasks([dict(_valid()[0], sandbox={})])
        assert any("sandbox" in e for e in errors)

    def test_sandbox_names_reject_traversal_and_absolute(self) -> None:
        for bad in ("../escape", "a/../b", "/abs", ""):
            errors = validate_tasks([dict(_valid()[0], sandbox={bad: "x"})])
            assert any("rejected" in e for e in errors), bad

    def test_nested_sandbox_names_are_legal(self) -> None:
        task = dict(_valid()[0], sandbox={"sub/dir/in.txt": "seed"})
        assert validate_tasks([task]) == []


class TestValidateGrader:
    def test_non_dict_grader(self) -> None:
        errors = validate_tasks([dict(_valid()[0], grader=None)])
        assert any("grader must be an object" in e for e in errors)

    def test_unknown_type(self) -> None:
        grader = {"type": "psychic", "file": "out.txt"}
        errors = validate_tasks([dict(_valid()[0], grader=grader)])
        assert any("grader.type" in e for e in errors)

    def test_missing_file(self) -> None:
        grader = {"type": "exact", "expected": "x"}
        errors = validate_tasks([dict(_valid()[0], grader=grader)])
        assert any("grader.file" in e for e in errors)

    def test_exact_without_string_expected(self) -> None:
        grader = {"type": "exact", "file": "out.txt", "expected": 3}
        errors = validate_tasks([dict(_valid()[0], grader=grader)])
        assert any("expected" in e for e in errors)

    def test_contains_without_expected(self) -> None:
        grader = {"type": "contains", "file": "out.txt"}
        errors = validate_tasks([dict(_valid()[0], grader=grader)])
        assert any("expected" in e for e in errors)

    def test_json_field_requires_path_and_expected(self) -> None:
        base = {"type": "json_field", "file": "out.json"}
        for grader in (base, {**base, "path": "result"}, {**base, "expected": "x"}):
            errors = validate_tasks([dict(_valid()[0], grader=dict(grader))])
            assert errors, grader

    def test_code_stdout_requires_script(self) -> None:
        grader = {"type": "code_stdout", "file": "sol.py"}
        errors = validate_tasks([dict(_valid()[0], grader=grader)])
        assert any("script" in e for e in errors)

    def test_all_four_types_pass_when_wellformed(self) -> None:
        for grader in (
            {"type": "exact", "file": "a", "expected": "x"},
            {"type": "contains", "file": "a", "expected": "x"},
            {"type": "json_field", "file": "a", "path": "p", "expected": 1},
            {"type": "code_stdout", "file": "a.py", "script": "a.py", "expected": "1"},
        ):
            assert validate_tasks([dict(_valid()[0], grader=grader)]) == [], grader


class TestMaterialize:
    def test_writes_declared_files(self, tmp_path: Path) -> None:
        task = _valid()[0]
        sandbox = materialize(task, tmp_path)
        assert (sandbox / "in.txt").read_text(encoding="utf-8") == "seed"

    def test_creates_parent_dirs_for_nested_names(self, tmp_path: Path) -> None:
        task = dict(_valid()[0], sandbox={"sub/dir/in.txt": "deep"})
        sandbox = materialize(task, tmp_path)
        assert (sandbox / "sub" / "dir" / "in.txt").read_text(encoding="utf-8") == "deep"

    def test_force_deletes_undeclared_stale_files(self, tmp_path: Path) -> None:
        """The phantom-scoring defense: a leftover deliverable from a previous
        rollout must not survive into this materialization."""
        task = _valid()[0]
        sandbox = materialize(task, tmp_path)
        (sandbox / "out.txt").write_text("stale answer", encoding="utf-8")
        (sandbox / "cache").mkdir()
        (sandbox / "cache" / "junk").write_text("x", encoding="utf-8")

        materialize(task, tmp_path, force=True)
        assert not (sandbox / "out.txt").exists()
        assert not (sandbox / "cache").exists()
        assert (sandbox / "in.txt").exists()

    def test_force_off_keeps_stale_files(self, tmp_path: Path) -> None:
        task = _valid()[0]
        sandbox = materialize(task, tmp_path)
        (sandbox / "out.txt").write_text("stale answer", encoding="utf-8")
        materialize(task, tmp_path, force=False)
        assert (sandbox / "out.txt").exists()

    def test_rematerialization_is_idempotent(self, tmp_path: Path) -> None:
        task = _valid()[0]
        first = materialize(task, tmp_path)
        second = materialize(task, tmp_path)
        assert first == second
        assert (second / "in.txt").read_text(encoding="utf-8") == "seed"
