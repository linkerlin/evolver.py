"""Proxy router layer: model routing, feature flags, caching, and messages."""

from evolver.proxy.router.cache_passthrough import (
    CACHE_TTL_SECONDS,
    MAX_CACHE_SIZE,
    cache_stats,
    get_cached,
    invalidate_cache,
    set_cache,
)
from evolver.proxy.router.features import (
    FEATURE_FLAG_REFRESH_INTERVAL,
    get_disabled_routes,
    is_route_enabled,
    refresh_feature_flags,
)
from evolver.proxy.router.messages_route import (
    BEDROCK_MODEL_MAP,
    canonicalize_for_bedrock,
    handle_messages,
    proxy_anthropic,
    proxy_bedrock,
)
from evolver.proxy.router.model_router import (
    DEFAULT_MODEL_FALLBACKS,
    TIER_ORDER,
    get_upstream_preference,
    resolve_model,
    select_upstream_for_model,
)

__all__ = [
    # model_router
    "get_upstream_preference",
    "resolve_model",
    "select_upstream_for_model",
    "TIER_ORDER",
    "DEFAULT_MODEL_FALLBACKS",
    # features
    "refresh_feature_flags",
    "is_route_enabled",
    "get_disabled_routes",
    "FEATURE_FLAG_REFRESH_INTERVAL",
    # cache_passthrough
    "get_cached",
    "set_cache",
    "invalidate_cache",
    "cache_stats",
    "CACHE_TTL_SECONDS",
    "MAX_CACHE_SIZE",
    # messages_route
    "handle_messages",
    "proxy_anthropic",
    "proxy_bedrock",
    "canonicalize_for_bedrock",
    "BEDROCK_MODEL_MAP",
]
