"""Feature flags routing: dynamically enable/disable routes based on Hub flags.

Equivalent to evolver/src/proxy/router/features.js.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

FEATURE_FLAGS_PATH_ENV = "EVOMAP_FEATURE_FLAGS_PATH"
FEATURE_FLAG_REFRESH_INTERVAL = 30.0  # seconds

_default_flags: dict[str, bool] = {
    "enable_llm_review": False,
    "enable_auto_buyer": False,
    "enable_validator": True,
    "enable_recall_inject": False,
    "enable_curriculum": False,
    "enable_explore": False,
    "enable_skill_auto_update": False,
    "enable_trace_upload": False,
}

_last_refresh: float = 0.0
_cached_flags: dict[str, bool] = dict(_default_flags)


def _flags_path() -> Path | None:
    env = os.environ.get(FEATURE_FLAGS_PATH_ENV)
    if env:
        return Path(env)
    p = Path.home() / ".evomap" / "feature_flags.json"
    return p if p.exists() else None


def _load_disk_flags() -> dict[str, bool]:
    path = _flags_path()
    if path is None:
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            return {k: bool(v) for k, v in data.items() if isinstance(v, bool)}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def refresh_feature_flags() -> dict[str, bool]:
    """Reload feature flags from all sources (env > disk > default).

    Flags changed via env var take immediate effect.
    Disk flags are refreshed every 30s.
    """
    global _last_refresh, _cached_flags

    now = time.time()
    flags = dict(_default_flags)

    # Layer 1: disk (with cache)
    if now - _last_refresh >= FEATURE_FLAG_REFRESH_INTERVAL:
        disk = _load_disk_flags()
        flags.update(disk)
        _last_refresh = now
    else:
        flags.update({k: v for k, v in _cached_flags.items() if k not in flags})

    # Layer 2: env (always wins)
    env_prefix = "EVOLVER_FF_"
    for key, val in os.environ.items():
        if key.startswith(env_prefix):
            flag_name = key[len(env_prefix) :].lower()
            flags[flag_name] = val.lower() in ("1", "true", "on", "yes")

    _cached_flags = flags
    return flags


def is_route_enabled(route_name: str) -> bool:
    """Check if a named route is enabled by feature flags.

    Unknown routes default to enabled.
    """
    flags = refresh_feature_flags()

    route_flag_map = {
        "llm_messages": "enable_llm_review",
        "atp_order": "enable_auto_buyer",
        "validator_tasks": "enable_validator",
        "skill_update": "enable_skill_auto_update",
        "trace_upload": "enable_trace_upload",
    }

    flag = route_flag_map.get(route_name)
    if flag is None:
        return True
    return flags.get(flag, True)


def get_disabled_routes() -> list[str]:
    """Return a list of currently disabled route names."""
    flags = refresh_feature_flags()
    disabled = []
    for route, flag in {
        "llm_messages": "enable_llm_review",
        "atp_order": "enable_auto_buyer",
        "validator_tasks": "enable_validator",
        "skill_update": "enable_skill_auto_update",
        "trace_upload": "enable_trace_upload",
    }.items():
        if not flags.get(flag, True):
            disabled.append(route)
    return disabled


__all__ = [
    "FEATURE_FLAG_REFRESH_INTERVAL",
    "get_disabled_routes",
    "is_route_enabled",
    "refresh_feature_flags",
]
