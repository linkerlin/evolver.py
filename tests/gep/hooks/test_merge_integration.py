"""Tests for evolver.gep.hooks.merge_integration (Sprint C3)."""

from __future__ import annotations

from evolver.gep.hooks.merge_integration import merge_accepted_candidates

_BASE = """\
import os

def foo():
    return 1


def bar():
    return 2
"""


def _cand_foo() -> str:
    return _BASE.replace("    return 1", "    return 10")


def _cand_bar() -> str:
    return _BASE.replace("    return 2", "    return 20")


class TestMergeAcceptedCandidates:
    def test_merges_same_path(self) -> None:
        result = merge_accepted_candidates(
            [
                {"path": "src/mod.py", "base": _BASE, "candidate": _cand_foo()},
                {"path": "src/mod.py", "base": _BASE, "candidate": _cand_bar()},
            ]
        )
        assert len(result) == 1
        assert result[0]["conflict"] is None
        merged = result[0]["merged_source"]
        assert "    return 10" in merged
        assert "    return 20" in merged

    def test_separate_paths_separate_results(self) -> None:
        result = merge_accepted_candidates(
            [
                {"path": "a.py", "base": _BASE, "candidate": _cand_foo()},
                {"path": "b.py", "base": _BASE, "candidate": _cand_bar()},
            ]
        )
        assert {r["path"] for r in result} == {"a.py", "b.py"}

    def test_conflict_reported_not_raised(self) -> None:
        cand_a = _cand_foo().replace("    return 10", "    return 100")
        cand_b = _cand_foo().replace("    return 10", "    return 1000")
        result = merge_accepted_candidates(
            [
                {"path": "m.py", "base": _BASE, "candidate": cand_a},
                {"path": "m.py", "base": _BASE, "candidate": cand_b},
            ]
        )
        assert result[0]["merged_source"] is None
        assert "conflicting edits" in (result[0]["conflict"] or "")

    def test_invalid_entries_skipped(self) -> None:
        result = merge_accepted_candidates(
            [
                {"path": "a.py", "base": _BASE, "candidate": _cand_foo()},
                {"path": "b.py"},  # missing base/candidate
                "not-a-dict",
                {"path": "c.py", "base": 42, "candidate": "x"},  # non-str base
            ]
        )
        assert len(result) == 1
        assert result[0]["path"] == "a.py"

    def test_empty_input(self) -> None:
        assert merge_accepted_candidates([]) == []
