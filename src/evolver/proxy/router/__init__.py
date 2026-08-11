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
    "BEDROCK_MODEL_MAP",
    "CACHE_TTL_SECONDS",
    "DEFAULT_MODEL_FALLBACKS",
    "FEATURE_FLAG_REFRESH_INTERVAL",
    "MAX_CACHE_SIZE",
    "TIER_ORDER",
    "cache_stats",
    "canonicalize_for_bedrock",
    # cache_passthrough
    "get_cached",
    "get_disabled_routes",
    # model_router
    "get_upstream_preference",
    # messages_route
    "handle_messages",
    "invalidate_cache",
    "is_route_enabled",
    "proxy_anthropic",
    "proxy_bedrock",
    # features
    "refresh_feature_flags",
    "resolve_model",
    "select_upstream_for_model",
    "set_cache",
]
