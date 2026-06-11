"""Tests for evolver.gep.hub_fetch."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from evolver.gep.hub_fetch import (
    CircuitBreaker,
    _cache,
    _cache_key,
    _get_cached,
    _set_cached,
    clear_cache,
    hub_fetch,
    hub_get,
    hub_post,
    reset_circuit_breaker,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


class TestCacheKey:
    def test_stable(self):
        a = _cache_key("GET", "https://h/a", {"x": 1}, None)
        b = _cache_key("GET", "https://h/a", {"x": 1}, None)
        assert a == b

    def test_differs_on_params(self):
        a = _cache_key("GET", "https://h/a", {"x": 1}, None)
        b = _cache_key("GET", "https://h/a", {"x": 2}, None)
        assert a != b


class TestCache:
    def test_basic_set_get(self):
        _set_cached("k1", {"a": 1})
        assert _get_cached("k1", ttl=10) == {"a": 1}

    def test_ttl_expires(self):

        _set_cached("k2", {"a": 2})
        assert _get_cached("k2", ttl=-1) is None

    def test_miss(self):
        assert _get_cached("noexist", ttl=60) is None

    def test_clear(self):
        _set_cached("k3", 1)
        clear_cache()
        assert _get_cached("k3", ttl=60) is None

    def test_lru_eviction(self):
        for i in range(110):
            _set_cached(f"k{i}", i)
        assert len(_cache) == 100


class TestCircuitBreaker:
    def test_closed_by_default(self):
        cb = CircuitBreaker()
        assert cb.can_attempt()

    def test_opens_after_threshold(self):
        cb = CircuitBreaker()
        for _ in range(5):
            cb.record_failure()
        assert cb.state == "open"
        assert not cb.can_attempt()

    def test_half_open_then_close(self):
        cb = CircuitBreaker()
        for _ in range(5):
            cb.record_failure()
        assert cb.state == "open"
        # Manually set last_failure far back so recovery triggers half_open
        cb.last_failure = 0
        assert cb.can_attempt()
        assert cb.state == "half_open"
        cb.record_success()
        assert cb.state == "closed"

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker()
        for _ in range(5):
            cb.record_failure()
        cb.last_failure = 0
        cb.can_attempt()  # half_open
        cb.record_failure()
        assert cb.state == "open"


class TestHubFetch:
    @respx.mock
    def test_success_and_cache(self):
        route = respx.get("https://hub.example/svc").mock(
            return_value=Response(200, json={"ok": True})
        )
        r = hub_fetch("https://hub.example/svc")
        assert r == {"ok": True}
        assert route.called

        # Cached — second call should not hit network
        route.reset()
        r2 = hub_fetch("https://hub.example/svc")
        assert r2 == {"ok": True}
        assert route.call_count == 0

    @respx.mock
    def test_retry_then_success(self):
        route = respx.get("https://hub.example/fail").mock(
            side_effect=[Response(500), Response(500), Response(200, json={"recovered": True})]
        )
        r = hub_fetch("https://hub.example/fail", backoff_base=0.01, max_retries=3)
        assert r == {"recovered": True}
        assert route.call_count == 3

    @respx.mock
    def test_retry_exhausted(self):
        route = respx.get("https://hub.example/boom").mock(return_value=Response(500))
        with pytest.raises(RuntimeError, match="Hub fetch failed"):
            hub_fetch("https://hub.example/boom", backoff_base=0.01, max_retries=1)
        assert route.call_count == 2

    @respx.mock
    def test_post_no_cache(self):
        route = respx.post("https://hub.example/action").mock(
            return_value=Response(200, json={"done": True})
        )
        r = hub_post("https://hub.example/action", json_body={"x": 1})
        assert r == {"done": True}
        assert route.called

        # Second POST should still hit network
        route.reset()
        hub_post("https://hub.example/action", json_body={"x": 1})
        assert route.called

    @respx.mock
    def test_hub_get_convenience(self):
        route = respx.get("https://hub.example/search").mock(
            return_value=Response(200, json={"hits": []})
        )
        assert hub_get("https://hub.example/search", params={"q": "abc"}) == {"hits": []}
        assert route.called

    @respx.mock
    def test_circuit_breaker_opens(self):
        reset_circuit_breaker()
        route = respx.get("https://hub.example/cb").mock(return_value=Response(500))
        # Fail 5 times to trip the breaker
        for _ in range(5):
            with pytest.raises(RuntimeError, match="Hub fetch failed"):
                hub_fetch("https://hub.example/cb", backoff_base=0.01, max_retries=0)
        # Next attempt should be rejected by open breaker
        with pytest.raises(RuntimeError, match="Circuit breaker is OPEN"):
            hub_fetch("https://hub.example/cb", backoff_base=0.01, max_retries=0)
        assert route.call_count == 5
