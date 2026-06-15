"""Proxy settings persistence — save/load Proxy configuration.

Equivalent to ``evolver/src/proxy/server/settings.js``.

Stores Hub URL, auth token, upstream preference, and model overrides in an
atomic JSON file at ``~/.evomap/proxy-settings.json``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_SETTINGS_PATH = Path.home() / ".evomap" / "proxy-settings.json"

_DEFAULTS: dict[str, Any] = {
    "hub_url": "",
    "upstream": "anthropic",
    "model_overrides": {},
    "port": 8081,
}


def get_settings_path() -> Path:
    return Path(os.environ.get("EVOLVER_PROXY_SETTINGS_PATH", DEFAULT_SETTINGS_PATH))


def load_settings() -> dict[str, Any]:
    """Load proxy settings from disk, merged with defaults."""
    path = get_settings_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged = dict(_DEFAULTS)
                merged.update(data)
                return merged
    except (OSError, json.JSONDecodeError):
        pass
    return dict(_DEFAULTS)


def save_settings(settings: dict[str, Any]) -> None:
    """Atomically save proxy settings to disk."""
    path = get_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    tmp.replace(path)


def get_setting(key: str, default: Any = None) -> Any:
    """Get a single setting value."""
    return load_settings().get(key, default)


def set_setting(key: str, value: Any) -> None:
    """Set and persist a single setting."""
    settings = load_settings()
    settings[key] = value
    save_settings(settings)


__all__ = [
    "DEFAULT_SETTINGS_PATH",
    "get_setting",
    "get_settings_path",
    "load_settings",
    "save_settings",
    "set_setting",
]
