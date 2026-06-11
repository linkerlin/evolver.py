"""Tests for evolver.gep.candidate_eval."""

import pytest

from evolver.gep.candidate_eval import (
    Candidate,
    evaluate_candidate,
    pick_best,
    rank_candidates,
)


class TestEvaluateCandidate:
    def test_basic_scoring(self):
        c = Candidate(diff_text="diff --git a/foo.py b/foo.py\n+line1\n+line2")
        score = evaluate_candidate(c)
        assert score is not None
        assert 0 <= score.complexity <= 1
        assert 0 <= score.risk <= 1
        assert 0 <= score.test_coverage <= 1
        assert 0 <= score.composite <= 1

    def test_test_coverage(self):
        c = Candidate(diff_text="diff --git a/tests/test_foo.py b/tests/test_foo.py\n+def test(): pass")
        score = evaluate_candidate(c)
        assert score.test_coverage > 0

    def test_novelty_high_for_unique(self):
        c = Candidate(diff_text="unique diff content xyz")
        score = evaluate_candidate(c, recent_diffs=[])
        assert score.novelty == 1.0

    def test_novelty_low_for_similar(self):
        diff = "same diff content"
        c = Candidate(diff_text=diff)
        score = evaluate_candidate(c, recent_diffs=[diff])
        assert score.novelty < 1.0


class TestRankCandidates:
    def test_sorts_by_composite(self):
        c1 = Candidate(diff_text="a")
        c2 = Candidate(diff_text="b" * 5000)
        ranked = rank_candidates([c1, c2])
        assert ranked[0].score.composite >= ranked[1].score.composite

    def test_tournament_strategy(self):
        c1 = Candidate(diff_text="diff --git a/t.py b/t.py\n+def test(): pass")
        c2 = Candidate(diff_text="+" * 1000)
        ranked = rank_candidates([c1, c2], strategy="tournament")
        assert len(ranked) == 2
        assert ranked[0].score is not None


class TestPickBest:
    def test_returns_best(self):
        c1 = Candidate(diff_text="a")
        c2 = Candidate(diff_text="b" * 5000)
        best = pick_best([c1, c2])
        assert best is not None
        assert best.candidate_id in (c1.candidate_id, c2.candidate_id)

    def test_min_score_filters(self):
        c = Candidate(diff_text="+" * 10000)
        best = pick_best([c], min_score=1.0)
        # Composite is unlikely to be 1.0 for a huge diff
        assert best is None

    def test_empty_list(self):
        assert pick_best([]) is None
