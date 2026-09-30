"""Grader contracts (S26.1) — the four scorers, edge inputs, never crash.

1:1 with ``evolver.bench.scoring``. The graders are the pack gate's floor:
whatever the sandbox holds — missing files, broken JSON, wrong encodings —
a grader returns a float, never raises (wikiskill honesty).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from evolver.bench.scoring import grade


def _task(grader: dict[str, Any]) -> dict[str, Any]:
    return {"id": "t", "split": "val", "title": "t", "prompt": "p", "sandbox": {}, "grader": grader}


def _write(sandbox: Path, name: str, content: str) -> None:
    sandbox.mkdir(parents=True, exist_ok=True)
    (sandbox / name).write_text(content, encoding="utf-8")


class TestExactGrader:
    def test_expected_written_back_scores_one(self, tmp_path: Path) -> None:
        task = _task({"type": "exact", "file": "out.txt", "expected": "gamma|7|active"})
        _write(tmp_path, "out.txt", "gamma|7|active")
        assert grade(task, tmp_path) == 1.0

    def test_trailing_whitespace_and_outer_blank_lines_are_normalized(self, tmp_path: Path) -> None:
        # Line-TRAILING whitespace and leading/trailing blank lines normalize
        # away; line-leading whitespace and interior blank lines are content.
        task = _task({"type": "exact", "file": "out.txt", "expected": "a\nb"})
        _write(tmp_path, "out.txt", "a  \nb  \n\n")
        assert grade(task, tmp_path) == 1.0

    def test_interior_blank_lines_are_significant(self, tmp_path: Path) -> None:
        task = _task({"type": "exact", "file": "out.txt", "expected": "a\nb"})
        _write(tmp_path, "out.txt", "a\n\nb")
        assert grade(task, tmp_path) == 0.0

    def test_wrong_answer_scores_zero(self, tmp_path: Path) -> None:
        task = _task({"type": "exact", "file": "out.txt", "expected": "a"})
        _write(tmp_path, "out.txt", "b")
        assert grade(task, tmp_path) == 0.0

    def test_missing_deliverable_scores_zero(self, tmp_path: Path) -> None:
        task = _task({"type": "exact", "file": "out.txt", "expected": "a"})
        assert grade(task, tmp_path) == 0.0

    def test_case_is_significant(self, tmp_path: Path) -> None:
        task = _task({"type": "exact", "file": "out.txt", "expected": "Cain"})
        _write(tmp_path, "out.txt", "cain")
        assert grade(task, tmp_path) == 0.0


class TestContainsGrader:
    def test_substring_anywhere_scores_one(self, tmp_path: Path) -> None:
        task = _task({"type": "contains", "file": "log.txt", "expected": "needle"})
        _write(tmp_path, "log.txt", "hay needle hay")
        assert grade(task, tmp_path) == 1.0

    def test_absent_substring_scores_zero(self, tmp_path: Path) -> None:
        task = _task({"type": "contains", "file": "log.txt", "expected": "needle"})
        _write(tmp_path, "log.txt", "hay only")
        assert grade(task, tmp_path) == 0.0

    def test_missing_file_scores_zero(self, tmp_path: Path) -> None:
        task = _task({"type": "contains", "file": "log.txt", "expected": "x"})
        assert grade(task, tmp_path) == 0.0


class TestJsonFieldGrader:
    def test_nested_path_is_followed(self, tmp_path: Path) -> None:
        task = _task(
            {"type": "json_field", "file": "out.json", "path": "result", "expected": "degraded"}
        )
        _write(tmp_path, "out.json", '{"result": "degraded"}')
        assert grade(task, tmp_path) == 1.0

    def test_list_indices_are_followed(self, tmp_path: Path) -> None:
        task = _task({"type": "json_field", "file": "out.json", "path": "items.1", "expected": 7})
        _write(tmp_path, "out.json", '{"items": [3, 7]}')
        assert grade(task, tmp_path) == 1.0

    def test_wrong_value_scores_zero(self, tmp_path: Path) -> None:
        task = _task({"type": "json_field", "file": "out.json", "path": "result", "expected": "up"})
        _write(tmp_path, "out.json", '{"result": "down"}')
        assert grade(task, tmp_path) == 0.0

    def test_missing_key_never_crashes(self, tmp_path: Path) -> None:
        task = _task({"type": "json_field", "file": "out.json", "path": "nope", "expected": "x"})
        _write(tmp_path, "out.json", '{"result": "degraded"}')
        assert grade(task, tmp_path) == 0.0

    def test_broken_json_scores_zero(self, tmp_path: Path) -> None:
        task = _task({"type": "json_field", "file": "out.json", "path": "result", "expected": "x"})
        _write(tmp_path, "out.json", "{not json")
        assert grade(task, tmp_path) == 0.0


class TestCodeStdoutGrader:
    def test_matching_stdout_scores_one(self, tmp_path: Path) -> None:
        task = _task(
            {"type": "code_stdout", "file": "sol.py", "script": "sol.py", "expected": "120"}
        )
        _write(tmp_path, "sol.py", "print(120)")
        assert grade(task, tmp_path) == 1.0

    def test_extra_stdout_whitespace_is_normalized(self, tmp_path: Path) -> None:
        task = _task({"type": "code_stdout", "file": "sol.py", "script": "sol.py", "expected": "3"})
        _write(tmp_path, "sol.py", "print('  3  \\n\\n')")
        assert grade(task, tmp_path) == 1.0

    def test_wrong_stdout_scores_zero(self, tmp_path: Path) -> None:
        task = _task({"type": "code_stdout", "file": "sol.py", "script": "sol.py", "expected": "3"})
        _write(tmp_path, "sol.py", "print(4)")
        assert grade(task, tmp_path) == 0.0

    def test_crashing_script_scores_zero(self, tmp_path: Path) -> None:
        task = _task({"type": "code_stdout", "file": "sol.py", "script": "sol.py", "expected": "3"})
        _write(tmp_path, "sol.py", "raise SystemExit(1)")
        assert grade(task, tmp_path) == 0.0

    def test_missing_script_scores_zero(self, tmp_path: Path) -> None:
        task = _task({"type": "code_stdout", "file": "sol.py", "script": "sol.py", "expected": "3"})
        assert grade(task, tmp_path) == 0.0

    def test_script_runs_with_the_sandbox_as_cwd(self, tmp_path: Path) -> None:
        # The script reads a sandbox file with a relative path — the grade
        # only works if the runner executed it inside the sandbox.
        task = _task(
            {"type": "code_stdout", "file": "sol.py", "script": "sol.py", "expected": "seed"}
        )
        _write(tmp_path, "input.txt", "seed")
        _write(tmp_path, "sol.py", "print(open('input.txt').read())")
        assert grade(task, tmp_path) == 1.0


class TestGraderRobustness:
    def test_unknown_grader_type_scores_zero(self, tmp_path: Path) -> None:
        task = _task({"type": "psychic", "file": "out.txt"})
        _write(tmp_path, "out.txt", "anything")
        assert grade(task, tmp_path) == 0.0

    def test_missing_grader_scores_zero(self, tmp_path: Path) -> None:
        task = _task({})
        _write(tmp_path, "out.txt", "anything")
        assert grade(task, tmp_path) == 0.0

    def test_undecodable_bytes_do_not_crash(self, tmp_path: Path) -> None:
        task = _task({"type": "exact", "file": "out.txt", "expected": "x"})
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "out.txt").write_bytes(b"\xff\xfe\x00broken")
        assert grade(task, tmp_path) == 0.0

    def test_scores_are_always_in_unit_interval(self, tmp_path: Path) -> None:
        for grader in (
            {"type": "exact", "file": "a.txt", "expected": "a"},
            {"type": "contains", "file": "a.txt", "expected": "a"},
            {"type": "json_field", "file": "a.json", "path": "x", "expected": 1},
            {"type": "code_stdout", "file": "a.py", "script": "a.py", "expected": "a"},
        ):
            score = grade(_task(grader), tmp_path)
            assert isinstance(score, float) and 0.0 <= score <= 1.0, (grader, score)
