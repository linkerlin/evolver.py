"""Tests for evolver.gep.hooks.ast_merge (Sprint C3)."""

from __future__ import annotations

import ast

import pytest

from evolver.gep.hooks.ast_merge import (
    MergeConflictError,
    apply_function_definition,
    changed_top_level_functions,
    function_sources,
    merge_candidate_changes,
    top_level_function_spans,
    top_level_order,
)

_BASE = """\
import os

def foo():
    return 1


def bar():
    return 2


GLOBAL = 42
"""


def _cand_foo() -> str:
    return _BASE.replace("    return 1", "    return 10")


def _cand_bar() -> str:
    return _BASE.replace("    return 2", "    return 20")


class TestTopLevelFunctionSpans:
    def test_spans_include_decorators(self) -> None:
        src = (
            "@decorator\n"
            "def f():\n"
            "    return 1\n"
            "\n"
            "def g():\n"
            "    return 2\n"
        )
        spans = top_level_function_spans(src)
        assert spans["f"] == (1, 3)  # decorator line included
        assert spans["g"] == (5, 6)

    def test_async_function(self) -> None:
        src = "async def f():\n    return 1\n"
        assert top_level_function_spans(src)["f"] == (1, 2)

    def test_invalid_source_raises(self) -> None:
        with pytest.raises(SyntaxError):
            top_level_function_spans("def broken(:\n")


class TestChangedTopLevelFunctions:
    def test_changed_function_detected(self) -> None:
        changed = changed_top_level_functions(_BASE, _cand_foo())
        assert changed == ["foo"]

    def test_multiple_changes(self) -> None:
        both = _cand_foo().replace("    return 2", "    return 20")
        changed = changed_top_level_functions(_BASE, both)
        assert set(changed) == {"foo", "bar"}

    def test_no_changes(self) -> None:
        assert changed_top_level_functions(_BASE, _BASE) == []

    def test_deletion_rejected(self) -> None:
        deleted = _BASE.replace(
            "def bar():\n    return 2\n\n\n", ""
        )
        with pytest.raises(MergeConflictError, match="deleted top-level function"):
            changed_top_level_functions(_BASE, deleted)

    def test_non_function_change_rejected(self) -> None:
        changed_global = _BASE.replace("GLOBAL = 42", "GLOBAL = 43")
        with pytest.raises(MergeConflictError, match="non-function top-level"):
            changed_top_level_functions(_BASE, changed_global)

    def test_new_function_allowed(self) -> None:
        added = _BASE + "\ndef baz():\n    return 3\n"
        # adding a new function is not a deletion nor a non-function change
        changed = changed_top_level_functions(_BASE, added)
        assert "baz" not in changed  # new functions aren't 'changes' to merge


class TestApplyFunctionDefinition:
    def test_replace_existing(self) -> None:
        new_foo = _cand_foo()
        # extract the foo source from the candidate
        foo_src = _slice_func(new_foo, "foo")
        result = apply_function_definition(_BASE, "foo", foo_src)
        assert "    return 10" in result
        assert "    return 2" in result  # bar untouched

    def test_insert_new_function(self) -> None:
        added = _BASE + "\ndef baz():\n    return 3\n"
        baz_src = _slice_func(added, "baz")
        result = apply_function_definition(
            _BASE, "baz", baz_src, cand_order=top_level_order(added)
        )
        assert "def baz():" in result
        # inserted after its predecessor (bar) in candidate order
        assert result.index("def bar") < result.index("def baz")


def _slice_func(source: str, name: str) -> str:
    return function_sources(source, top_level_function_spans(source))[name]


class TestMergeCandidateChanges:
    def test_merge_disjoint_functions(self) -> None:
        merged = merge_candidate_changes(_BASE, [_cand_foo(), _cand_bar()])
        assert "    return 10" in merged  # foo updated
        assert "    return 20" in merged  # bar updated
        assert "GLOBAL = 42" in merged  # non-function code preserved

    def test_merge_keeps_source_valid(self) -> None:
        merged = merge_candidate_changes(_BASE, [_cand_foo(), _cand_bar()])
        ast.parse(merged)  # must remain valid Python

    def test_conflict_on_same_function(self) -> None:
        # two candidates both edit foo differently
        cand_a = _cand_foo().replace("    return 10", "    return 100")
        cand_b = _cand_foo().replace("    return 10", "    return 1000")
        with pytest.raises(MergeConflictError, match="conflicting edits to function 'foo'"):
            merge_candidate_changes(_BASE, [cand_a, cand_b])

    def test_same_edit_not_conflict(self) -> None:
        # both candidates make the IDENTICAL change → not a conflict
        merged = merge_candidate_changes(_BASE, [_cand_foo(), _cand_foo()])
        assert "    return 10" in merged

    def test_empty_candidates_returns_base(self) -> None:
        assert merge_candidate_changes(_BASE, []) == _BASE

    def test_merge_new_function_from_candidate(self) -> None:
        cand = _cand_foo() + "\ndef baz():\n    return 3\n"
        merged = merge_candidate_changes(_BASE, [cand])
        assert "def baz():" in merged
        assert "    return 10" in merged
