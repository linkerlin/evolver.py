"""Regression tests for the stale-snapshot false kill (round-77, DEBUG #46)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.gep.acceptance import t0_frozen
from evolver.gep.acceptance.t0_frozen import run_pass_rate


@pytest.fixture
def repo_with_tests(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    test_file = repo / "tests" / "test_a.py"
    test_file.write_text("def test_one():\n    assert True\n")
    _git_init(repo)
    return repo


def _git_init(repo: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)


class TestStaleIdFiltering:
    def test_stale_ids_filtered_and_denominator_stable(
        self, repo_with_tests: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        frozen_ids = [
            "tests/dead/test_old.py::test_gone",
            "tests/test_a.py::test_one",
        ]
        monkeypatch.setattr(
            t0_frozen,
            "discover_test_ids",
            lambda cwd, **kw: ["tests/test_a.py::test_one"],
        )

        passed, total = run_pass_rate(frozen_ids, repo_with_tests)
        assert total == 2, "frozen denominator stays stable"
        assert passed == 1, (
            "stale (deleted) ID counts as failed — a deleted frozen test is "
            "itself a regression, preserving the test_gate_missing_ids contract"
        )

    def test_stale_chunk_does_not_zero_survivors(
        self, repo_with_tests: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The live failure: a chunk whose FIRST ID is stale made pytest
        # rc=4 "not found" and scored the WHOLE chunk as 0. With rc=4
        # handling, the survivor is dropped from the dead set and measured.
        frozen_ids = ["tests/dead/test_old.py::test_gone", "tests/test_a.py::test_one"]
        monkeypatch.setattr(
            t0_frozen,
            "discover_test_ids",
            lambda cwd, **kw: ["tests/test_a.py::test_one"],
        )
        passed, total = run_pass_rate(frozen_ids, repo_with_tests)
        assert passed == 1, "the surviving test must actually run and count"
        assert total == 2
