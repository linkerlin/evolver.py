"""Hub fetch client — resilient Hub data fetching with retry, cache, and circuit breaker.

Equivalent to Node's ``evolver/src/gep/hubFetch.js``.

Wraps all Hub HTTP calls with:
1. **In-memory cache** — TTL default 5 min, keyed by URL.
2. **Exponential backoff retry** — 3 retries, base 1 s, max 30 s.
3. **Circuit breaker** — open after 5 consecutive failures, half-open
   after 30 s, close on success.

Design notes
------------
* Thread-safe via ``threading.Lock``.
* Uses ``httpx`` for HTTP.
* Cache eviction: LRU with max 100 entries.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, cast

import httpx

logger = logging.getLogger(__name__)

DEFAULT_CACHE_TTL = 300.0  # 5 min
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 1.0
DEFAULT_BACKOFF_MAX = 30.0

# Circuit breaker
CB_FAILURE_THRESHOLD = 5
CB_RECOVERY_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    data: Any
    timestamp: float


@dataclass
class CircuitBreaker:
    state: str = "closed"  # closed | open | half_open
    failures: int = 0
    last_failure: float = 0.0
    _lock = threading.Lock()

    def record_success(self) -> None:
        with self._lock:
            self.state = "closed"
            self.failures = 0

    def record_failure(self) -> bool:
        """Return True if breaker just opened."""
        with self._lock:
            self.failures += 1
            self.last_failure = time.time()
            if self.state == "half_open":
                self.state = "open"
                return True
            if self.failures >= CB_FAILURE_THRESHOLD:
                self.state = "open"
                return True
            return False

    def can_attempt(self) -> bool:
        with self._lock:
            if self.state == "closed":
                return True
            if self.state == "open":
                if time.time() - self.last_failure >= CB_RECOVERY_TIMEOUT:
                    self.state = "half_open"
                    return True
                return False
            # half_open
            return True


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_cache: dict[str, _CacheEntry] = {}
_cache_lock = threading.Lock()
_cb = CircuitBreaker()


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _cache_key(method: str, url: str, params: Any, body: Any) -> str:
    canonical = json.dumps(
        {"m": method, "u": url, "p": params, "b": body}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _get_cached(key: str, ttl: float) -> Any | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        if time.time() - entry.timestamp > ttl:
            del _cache[key]
            return None
        return entry.data


def _set_cached(key: str, data: Any) -> None:
    with _cache_lock:
        # Simple LRU: evict oldest if > 100 entries
        if len(_cache) >= 100:
            oldest = min(_cache, key=lambda k: _cache[k].timestamp)
            del _cache[oldest]
        _cache[key] = _CacheEntry(data=data, timestamp=time.time())


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# Core fetch
# ---------------------------------------------------------------------------


def hub_fetch(
    url: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    cache_ttl: float = DEFAULT_CACHE_TTL,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timeout: float = 15.0,
    use_cache: bool = True,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
) -> dict[str, Any]:
    """Fetch *url* from the Hub with retry, cache, and circuit breaker.

    Returns the JSON response dict, or raises on failure.
    """
    if not _cb.can_attempt():
        raise RuntimeError("Circuit breaker is OPEN")

    key = _cache_key(method, url, params, json_body)
    if use_cache and method.upper() == "GET":
        cached = _get_cached(key, cache_ttl)
        if cached is not None:
            return cast(dict[str, Any], cached)

    last_exc: Exception | None = None
    backoff = backoff_base

    for attempt in range(max_retries + 1):
        try:
            resp = httpx.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                headers=headers,
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            _cb.record_success()
            if use_cache and method.upper() == "GET":
                _set_cached(key, data)
            return cast(dict[str, Any], data)
        except Exception as exc:
            last_exc = exc
            logger.debug("[HubFetch] Attempt %d failed for %s: %s", attempt + 1, url, exc)
            if attempt < max_retries:
                time.sleep(backoff)
                backoff = min(DEFAULT_BACKOFF_MAX, backoff * 2)

    _cb.record_failure()
    raise RuntimeError(
        f"Hub fetch failed after {max_retries + 1} attempts: {last_exc}"
    ) from last_exc


def reset_circuit_breaker() -> None:
    _cb.state = "closed"
    _cb.failures = 0
    _cb.last_failure = 0.0


def hub_get(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    cache_ttl: float = DEFAULT_CACHE_TTL,
) -> dict[str, Any]:
    """Convenience wrapper for GET requests."""
    return hub_fetch(url, method="GET", params=params, headers=headers, cache_ttl=cache_ttl)


def hub_post(
    url: str,
    *,
    json_body: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Convenience wrapper for POST requests (no cache)."""
    return hub_fetch(url, method="POST", json_body=json_body, headers=headers, use_cache=False)
