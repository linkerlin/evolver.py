"""Tests for the post_cycle candidate-merge hook (Sprint C3)."""

from __future__ import annotations

import asyncio

from evolver.evolve.post_cycle import run_post_cycle_hooks

_BASE = "import os\n\ndef foo():\n    return 1\n\n\ndef bar():\n    return 2\n"


def _cand_foo(v: int) -> str:
    return _BASE.replace("    return 1", f"    return {v}")


def _cand_bar(v: int) -> str:
    return _BASE.replace("    return 2", f"    return {v}")


class TestPostCycleMergeHook:
    def test_no_accepted_candidates_unchanged(self) -> None:
        ctx = {"signals": ["log_error"]}
        result = asyncio.run(run_post_cycle_hooks(dict(ctx)))
        assert "merged_candidates" not in result

    def test_single_accepted_candidate_no_merge(self) -> None:
        ctx = {
            "signals": ["log_error"],
            "accepted_candidates": [
                {"path": "m.py", "base": _BASE, "candidate": _cand_foo(10)}
            ],
        }
        result = asyncio.run(run_post_cycle_hooks(dict(ctx)))
        assert "merged_candidates" not in result  # <2 → skip

    def test_two_accepted_candidates_merged(self) -> None:
        ctx = {
            "signals": ["log_error"],
            "accepted_candidates": [
                {"path": "m.py", "base": _BASE, "candidate": _cand_foo(10)},
                {"path": "m.py", "base": _BASE, "candidate": _cand_bar(20)},
            ],
        }
        result = asyncio.run(run_post_cycle_hooks(dict(ctx)))
        merged = result["merged_candidates"]
        assert len(merged) == 1
        assert merged[0]["conflict"] is None
        assert "    return 10" in merged[0]["merged_source"]
        assert "    return 20" in merged[0]["merged_source"]

    def test_conflict_reported_in_ctx(self) -> None:
        ctx = {
            "signals": ["log_error"],
            "accepted_candidates": [
                {"path": "m.py", "base": _BASE, "candidate": _cand_foo(10)},
                {"path": "m.py", "base": _BASE, "candidate": _cand_foo(20)},
            ],
        }
        result = asyncio.run(run_post_cycle_hooks(dict(ctx)))
        merged = result["merged_candidates"]
        assert merged[0]["merged_source"] is None
        assert "conflicting edits" in (merged[0]["conflict"] or "")

    def test_identical_edits_not_conflict(self) -> None:
        ctx = {
            "signals": ["log_error"],
            "accepted_candidates": [
                {"path": "m.py", "base": _BASE, "candidate": _cand_foo(10)},
                {"path": "m.py", "base": _BASE, "candidate": _cand_foo(10)},
            ],
        }
        result = asyncio.run(run_post_cycle_hooks(dict(ctx)))
        merged = result["merged_candidates"]
        assert merged[0]["conflict"] is None
