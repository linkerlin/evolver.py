"""Tests for evolver.proxy.router.cache_passthrough."""

from __future__ import annotations

import time

import pytest

from evolver.proxy.router.cache_passthrough import (
    CACHE_TTL_SECONDS,
    MAX_CACHE_SIZE,
    cache_stats,
    get_cached,
    invalidate_cache,
    set_cache,
)


class TestCacheBasics:
    def test_get_cached_miss(self):
        assert get_cached({"model": "claude-3", "messages": []}) is None

    def test_set_and_get(self):
        body = {"model": "claude-3", "messages": [{"role": "user", "content": "hi"}]}
        response = {"content": [{"type": "text", "text": "hello"}]}
        set_cache(body, response)
        assert get_cached(body) == response

    def test_different_bodies_different_keys(self):
        body1 = {"model": "claude-3", "messages": [{"role": "user", "content": "hi"}]}
        body2 = {"model": "claude-3", "messages": [{"role": "user", "content": "hello"}]}
        set_cache(body1, {"text": "A"})
        set_cache(body2, {"text": "B"})
        assert get_cached(body1) == {"text": "A"}
        assert get_cached(body2) == {"text": "B"}

    def test_temperature_excluded_from_key(self):
        """Temperature should not affect cache key."""
        body = {
            "model": "claude-3",
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.7,
        }
        set_cache(body, {"text": "cached"})
        body_no_temp = {
            "model": "claude-3",
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.9,
        }
        assert get_cached(body_no_temp) == {"text": "cached"}

    def test_cache_expiration(self, monkeypatch: pytest.MonkeyPatch):
        body = {"model": "claude-3", "messages": [{"role": "user", "content": "hi"}]}
        set_cache(body, {"text": "old"})
        # Fast-forward time by a fixed amount
        original_time = time.time()
        monkeypatch.setattr(time, "time", lambda: original_time + CACHE_TTL_SECONDS + 1)
        assert get_cached(body) is None

    def test_invalidate_cache(self):
        invalidate_cache()  # Clean slate
        body = {"model": "claude-3", "messages": []}
        set_cache(body, {"text": "x"})
        count = invalidate_cache()
        assert count == 1
        assert get_cached(body) is None

    def test_invalidate_empty(self):
        invalidate_cache()  # Clean slate
        count = invalidate_cache()
        assert count == 0


class TestCacheStats:
    def test_empty_stats(self):
        invalidate_cache()
        stats = cache_stats()
        assert stats["total_entries"] == 0
        assert stats["valid_entries"] == 0
        assert stats["ttl_seconds"] == CACHE_TTL_SECONDS
        assert stats["max_size"] == MAX_CACHE_SIZE

    def test_with_entries(self):
        invalidate_cache()
        set_cache({"model": "a", "messages": []}, {"text": "1"})
        set_cache({"model": "b", "messages": []}, {"text": "2"})
        stats = cache_stats()
        assert stats["total_entries"] == 2
        assert stats["valid_entries"] == 2
        assert stats["expired_entries"] == 0

    def test_max_size_eviction(self):
        invalidate_cache()
        # Fill cache beyond capacity
        for i in range(MAX_CACHE_SIZE + 5):
            set_cache({"model": f"model-{i}", "messages": []}, {"text": str(i)})
        stats = cache_stats()
        assert stats["total_entries"] == MAX_CACHE_SIZE


class TestCacheConstants:
    def test_ttl_positive(self):
        assert CACHE_TTL_SECONDS > 0

    def test_max_size_reasonable(self):
        assert MAX_CACHE_SIZE >= 10
