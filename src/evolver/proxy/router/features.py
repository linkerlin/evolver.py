"""Feature flags routing — delegates to ``evolver.gep.feature_flags``.

Proxy route gating shares the same env / disk / default resolution as GEP
cognition (``EVOLVER_FF_*``, ``evolver/.config/disk_flags.json``, optional
``~/.evomap/feature_flags.json``).
"""

from __future__ import annotations

from evolver.gep.feature_flags import get_all_flags, invalidate_cache, is_enabled

# Kept for API compatibility (proxy modules may import this constant).
FEATURE_FLAG_REFRESH_INTERVAL = 30.0

ROUTE_FLAG_MAP: dict[str, str] = {
    "llm_messages": "enable_llm_review",
    "atp_order": "enable_auto_buyer",
    "validator_tasks": "enable_validator",
    "skill_update": "enable_skill_auto_update",
    "trace_upload": "enable_trace_upload",
}


def refresh_feature_flags() -> dict[str, bool]:
    """Return merged feature flags (same source as GEP ``get_all_flags()``)."""
    return get_all_flags()


def is_route_enabled(route_name: str) -> bool:
    """Check if a named proxy route is enabled by feature flags."""
    flag = ROUTE_FLAG_MAP.get(route_name)
    if flag is None:
        return True
    return is_enabled(flag)


def get_disabled_routes() -> list[str]:
    """Return proxy route names currently disabled by feature flags."""
    return [route for route, flag in ROUTE_FLAG_MAP.items() if not is_enabled(flag)]


__all__ = [
    "FEATURE_FLAG_REFRESH_INTERVAL",
    "ROUTE_FLAG_MAP",
    "get_disabled_routes",
    "invalidate_cache",
    "is_route_enabled",
    "refresh_feature_flags",
]
