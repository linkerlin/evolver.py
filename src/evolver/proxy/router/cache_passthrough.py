"""Cache passthrough: optimize LLM requests via short-term response caching.

Equivalent to evolver/src/proxy/router/cachePassthrough.js.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

CACHE_TTL_SECONDS = 300.0  # 5 minutes
MAX_CACHE_SIZE = 128

# In-memory cache: key -> (response_body, expires_at)
_cache: dict[str, tuple[Any, float]] = {}


def _canonicalize_request(body: dict[str, Any]) -> str:
    """Build a cache key from the request body.

    Excludes randomization parameters (temperature, top_p, etc.).
    Includes system + messages content.
    """
    system = body.get("system", "")
    messages = body.get("messages", [])
    model = body.get("model", "")

    canonical = {
        "model": model,
        "system": system,
        "messages": [{"role": m.get("role"), "content": m.get("content")} for m in messages],
    }
    raw = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_cached(body: dict[str, Any]) -> Any | None:
    """Return cached response if present and not expired."""
    key = _canonicalize_request(body)
    entry = _cache.get(key)
    if entry is None:
        return None
    response, expires_at = entry
    if time.time() > expires_at:
        del _cache[key]
        return None
    return response


def set_cache(body: dict[str, Any], response: Any) -> None:
    """Store a response in the cache."""
    key = _canonicalize_request(body)
    # Evict oldest if at capacity (simple FIFO eviction)
    if len(_cache) >= MAX_CACHE_SIZE:
        oldest = min(_cache.keys(), key=lambda k: _cache[k][1])
        del _cache[oldest]
    _cache[key] = (response, time.time() + CACHE_TTL_SECONDS)


def invalidate_cache() -> int:
    """Invalidate all cached entries. Returns count removed."""
    global _cache
    count = len(_cache)
    _cache.clear()
    return count


def cache_stats() -> dict[str, Any]:
    """Return cache statistics."""
    now = time.time()
    valid = sum(1 for _, expires in _cache.values() if expires > now)
    expired = len(_cache) - valid
    return {
        "total_entries": len(_cache),
        "valid_entries": valid,
        "expired_entries": expired,
        "ttl_seconds": CACHE_TTL_SECONDS,
        "max_size": MAX_CACHE_SIZE,
    }


__all__ = [
    "CACHE_TTL_SECONDS",
    "MAX_CACHE_SIZE",
    "cache_stats",
    "get_cached",
    "invalidate_cache",
    "set_cache",
]
