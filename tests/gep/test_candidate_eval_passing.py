"""Tests for candidate_eval.pick_passing (Self-Harness Sprint C2).

Asserts the function's contract (threshold filtering + ranked order) without
depending on the exact composite scale, which existing scoring normalizes to
a ~0.5-0.6 band for typical diffs.
"""

from __future__ import annotations

from evolver.gep.candidate_eval import (
    Candidate,
    pick_passing,
    rank_candidates,
)


def _candidates() -> list[Candidate]:
    return [
        Candidate(diff_text="a\n+b\n+c", description="small"),
        Candidate(diff_text="a\n-b\n-c\n-d\n-e", description="med"),
        Candidate(diff_text="a\n-b\n-c\n-d\n-e\n-f\n-g", description="big"),
    ]


class TestPickPassing:
    def test_zero_threshold_returns_all_ranked(self) -> None:
        candidates = _candidates()
        picked = pick_passing(candidates, threshold=0.0)
        ranked = rank_candidates(candidates)
        # same set, same best-first order
        assert [c.description for c in picked] == [c.description for c in ranked]

    def test_impossible_threshold_returns_none(self) -> None:
        # composite is normalized into [0,1] → 1.01 filters everything
        assert pick_passing(_candidates(), threshold=1.01) == []

    def test_threshold_is_monotonic(self) -> None:
        candidates = _candidates()
        low = pick_passing(candidates, threshold=0.3)
        high = pick_passing(candidates, threshold=0.6)
        assert len(high) <= len(low)
        # higher threshold keeps the best-ranked prefix
        if high:
            assert high[0].description == low[0].description

    def test_scores_attached(self) -> None:
        picked = pick_passing(_candidates(), threshold=0.0)
        assert all(c.score is not None for c in picked)
        # strictly descending composite
        composites = [c.score.composite for c in picked if c.score]
        assert composites == sorted(composites, reverse=True)

    def test_empty_input(self) -> None:
        assert pick_passing([]) == []

    def test_signal_vector_affects_ranking(self) -> None:
        candidates = [
            Candidate(diff_text="fix the timeout", description="hits_signal"),
            Candidate(diff_text="refactor unrelated", description="misses_signal"),
        ]
        picked = pick_passing(candidates, threshold=0.0, signal_vector={"fix": 1.0})
        # the diff mentioning "fix" matches the signal vector → ranks first
        assert picked[0].description == "hits_signal"
