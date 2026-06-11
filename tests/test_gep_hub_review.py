"""Tests for evolver.gep.hub_review."""

from __future__ import annotations

from evolver.gep.hub_review import (
    Verdict,
    review_patch,
    review_service_listing,
)


class TestReviewServiceListing:
    def test_valid_listing(self):
        svc = {
            "service_id": "s1",
            "title": "My Service",
            "description": "A great service that does things well.",
            "capabilities": ["add", "subtract"],
            "price_per_task": 5.0,
            "execution_mode": "sync",
        }
        r = review_service_listing(svc)
        assert r.verdict == Verdict.APPROVE
        assert r.score >= 80
        assert len(r.comments) == 0

    def test_short_title(self):
        svc = {
            "title": "Hi",
            "description": "A great service that does things well.",
            "capabilities": ["x"],
            "price_per_task": 0,
            "execution_mode": "async",
        }
        r = review_service_listing(svc)
        assert any("Title too short" in c.message for c in r.comments)
        assert r.score < 100

    def test_short_description(self):
        svc = {
            "title": "Good Title",
            "description": "Short.",
            "capabilities": ["x"],
            "price_per_task": 0,
            "execution_mode": "sync",
        }
        r = review_service_listing(svc)
        assert any("Description too short" in c.message for c in r.comments)

    def test_missing_price(self):
        svc = {
            "title": "Good Title",
            "description": "A great service that does things well.",
            "capabilities": ["x"],
            "execution_mode": "sync",
        }
        r = review_service_listing(svc)
        assert any("Missing price" in c.message for c in r.comments)

    def test_bad_price(self):
        svc = {
            "title": "Good Title",
            "description": "A great service that does things well.",
            "capabilities": ["x"],
            "price_per_task": -1,
            "execution_mode": "sync",
        }
        r = review_service_listing(svc)
        assert any("price_per_task must be" in c.message for c in r.comments)

    def test_reject_score(self):
        svc = {
            "title": "",
            "description": "",
            "capabilities": [],
            "price_per_task": -10,
            "execution_mode": "weird",
        }
        r = review_service_listing(svc)
        assert r.verdict == Verdict.REJECT
        assert r.score < 40


class TestReviewPatch:
    def test_approve_clean_diff(self):
        diff = "diff --git a/foo.py b/foo.py\n+print(1)\n"
        r = review_patch(diff, ["foo.py"])
        assert r.verdict == Verdict.APPROVE
        assert r.score >= 80

    def test_empty_diff(self):
        r = review_patch("", ["foo.py"])
        assert r.verdict == Verdict.REJECT
        assert r.score == 0

    def test_suspicious_pattern(self):
        diff = "diff --git a/foo.py b/foo.py\n+os.system('rm -rf /')\n"
        r = review_patch(diff, ["foo.py"])
        assert r.verdict == Verdict.REJECT
        assert any("os.system" in c.message for c in r.comments)

    def test_todo_marker(self):
        diff = "diff --git a/foo.py b/foo.py\n+# TODO: fix this\n"
        r = review_patch(diff, ["foo.py"])
        assert any("TODO" in c.message for c in r.comments)
