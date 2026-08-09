"""Tests for candidate_eval.pick_passing (Self-Harness Sprint C2)."""

from __future__ import annotations

from evolver.gep.candidate_eval import Candidate, pick_passing


class TestPickPassing:
    def test_returns_all_above_threshold_ranked(self) -> None:
        candidates = [
            Candidate(diff_text="a\n+b\n+c", description="small"),
            Candidate(diff_text="a\n-b\n-c\n-d\n-e", description="med"),
            Candidate(diff_text="a\n-b\n-c\n-d\n-e\n-f\n-g", description="big"),
        ]
        picked = pick_passing(candidates, threshold=0.5)
        # rank best-first by composite; all three score >= threshold here
        assert len(picked) == 3
        assert picked[0].description == "small"  # lowest complexity ranks best

    def test_threshold_filters_low_scores(self) -> None:
        candidates = [
            Candidate(diff_text="a\n+b\n+c", description="small"),
            Candidate(
                diff_text="a\n-b\n-c\n-d\n-e\n-f\n-g\n-h\n-i\n-j\n-k\n-l\n-m\n-n",
                description="huge_risky",
            ),
        ]
        picked = pick_passing(candidates, threshold=0.75)
        # only the small clean diff passes a high bar
        assert [c.description for c in picked] == ["small"]

    def test_empty_input(self) -> None:
        assert pick_passing([]) == []

    def test_empty_diff_scores_zero_excluded_at_high_threshold(self) -> None:
        candidates = [Candidate(diff_text="", description="noop")]
        assert pick_passing(candidates, threshold=0.1) == []

    def test_zero_threshold_returns_all(self) -> None:
        candidates = [Candidate(diff_text="", description="noop")]
        assert len(pick_passing(candidates, threshold=0.0)) == 1
