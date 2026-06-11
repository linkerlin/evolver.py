"""Tests for evolver.gep.hub_search."""

from __future__ import annotations

from evolver.gep.hub_search import _tfidf_similarity, _tokenize, search_services


class TestTokenize:
    def test_basic(self):
        assert _tokenize("Hello World!") == {"hello", "world"}

    def test_empty(self):
        assert _tokenize("") == set()


class TestTfidfSimilarity:
    def test_identical(self):
        corpus = ["hello world"]
        assert _tfidf_similarity("hello world", "hello world", corpus) > 0.9

    def test_unrelated(self):
        corpus = ["hello world", "foo bar"]
        assert _tfidf_similarity("hello world", "foo bar", corpus) == 0.0

    def test_empty(self):
        assert _tfidf_similarity("", "abc", []) == 0.0


class TestSearchServices:
    def test_basic_ranking(self):
        services = [
            {
                "service_id": "a",
                "title": "Image Resizer",
                "description": "Resize images fast.",
                "capabilities": ["resize"],
                "price_per_task": 1.0,
                "execution_mode": "sync",
            },
            {
                "service_id": "b",
                "title": "Text Summarizer",
                "description": "Summarize long text.",
                "capabilities": ["summarize"],
                "price_per_task": 2.0,
                "execution_mode": "async",
            },
        ]
        hits = search_services(services, "resize image", top_k=10)
        assert len(hits) == 2
        assert hits[0].service_id == "a"
        assert hits[0].score > hits[1].score

    def test_min_signal_filter(self):
        services = [
            {
                "service_id": "a",
                "title": "X",
                "description": "X.",
                "capabilities": [],
                "price_per_task": 0,
                "execution_mode": "sync",
                "uptime_rate": 0.1,
                "avg_response_ms": 5000,
                "success_rate": 0.0,
                "rating": 0,
                "reviews_count": 0,
            },
        ]
        hits = search_services(services, "x", min_signal=0.5)
        assert len(hits) == 0

    def test_top_k_limits(self):
        services = [
            {
                "service_id": str(i),
                "title": f"Svc {i}",
                "description": f"Desc {i}.",
                "capabilities": [],
                "price_per_task": 0,
                "execution_mode": "sync",
            }
            for i in range(20)
        ]
        hits = search_services(services, "svc", top_k=5)
        assert len(hits) == 5

    def test_signal_boost(self):
        services = [
            {
                "service_id": "a",
                "title": "Good Svc",
                "description": "Desc.",
                "capabilities": [],
                "price_per_task": 0,
                "execution_mode": "sync",
                "uptime_rate": 1.0,
                "avg_response_ms": 50,
                "success_rate": 1.0,
                "rating": 5.0,
                "reviews_count": 20,
            },
            {
                "service_id": "b",
                "title": "Bad Svc",
                "description": "Desc.",
                "capabilities": [],
                "price_per_task": 0,
                "execution_mode": "sync",
                "uptime_rate": 0.5,
                "avg_response_ms": 4000,
                "success_rate": 0.5,
                "rating": 2.0,
                "reviews_count": 1,
            },
        ]
        hits = search_services(services, "svc", top_k=10)
        assert hits[0].service_id == "a"
        assert hits[0].signals["signal"] > hits[1].signals["signal"]
