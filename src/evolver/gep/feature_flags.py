"""Three-layer feature-flag system — env → disk → default.

Equivalent to Node's ``FeatureFlags`` in ``evolver/src/gep/``.

Layer order (highest priority first):
1. **Environment** — ``EVOLVER_FF_<NAME>=1`` or ``EVOLVER_FF_<NAME>=0``.
2. **Disk** — ``evolver/.config/disk_flags.json`` (auto-created if missing).
3. **Default** — hard-coded safe defaults in this module.

Hot-reload: disk flags are reloaded on each read (cached for 10 s).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FLAG_PREFIX = "EVOLVER_FF_"
DISK_FLAG_FILENAME = "disk_flags.json"
DISK_FLAG_DIR = ".config"
DISK_FLAG_TTL = 10.0  # seconds

# Default flags — safe, conservative defaults
DEFAULT_FLAGS: dict[str, bool] = {
    "enable_llm_review": True,
    "enable_auto_buyer": False,
    "enable_validator": True,
    "enable_recall_inject": True,
    "enable_curriculum": False,
    "enable_explore": False,
    "enable_idle_scheduler": True,
    "enable_local_state_awareness": True,
    "enable_policy_check": True,
    "enable_secret_sanitize": True,
    "enable_memory_graph": True,
}

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_disk_flags: dict[str, bool] = {}
_disk_flags_mtime: float = 0.0
_disk_flags_loaded_at: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_config_dir() -> Path:
    """Return ``<workspace_root>/evolver/.config``."""
    from evolver.gep.paths import get_workspace_root

    return get_workspace_root() / "evolver" / DISK_FLAG_DIR


def _disk_flag_path() -> Path:
    return _get_config_dir() / DISK_FLAG_FILENAME


def _load_disk_flags(force: bool = False) -> dict[str, bool]:
    """Read disk flags from JSON; create default file if absent."""
    global _disk_flags, _disk_flags_mtime, _disk_flags_loaded_at

    path = _disk_flag_path()
    now = time.monotonic()

    with _lock:
        if not force and (now - _disk_flags_loaded_at) < DISK_FLAG_TTL:
            return _disk_flags.copy()

        if not path.exists():
            _get_config_dir().mkdir(parents=True, exist_ok=True)
            _write_disk_flags(DEFAULT_FLAGS)
            _disk_flags = DEFAULT_FLAGS.copy()
            _disk_flags_loaded_at = now
            return _disk_flags.copy()

        try:
            mtime = path.stat().st_mtime
            if not force and mtime == _disk_flags_mtime and (now - _disk_flags_loaded_at) < DISK_FLAG_TTL:
                return _disk_flags.copy()

            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            parsed = {k: bool(v) for k, v in raw.items() if isinstance(v, bool) or isinstance(v, int)}
            _disk_flags = parsed
            _disk_flags_mtime = mtime
            _disk_flags_loaded_at = now
            return _disk_flags.copy()
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[FeatureFlags] Failed to load disk flags: %s", exc)
            return _disk_flags.copy()


def _write_disk_flags(flags: dict[str, bool]) -> None:
    path = _disk_flag_path()
    _get_config_dir().mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(flags, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)
    logger.info("[FeatureFlags] Wrote disk flags to %s", path)


def _env_flag_value(name: str) -> bool | None:
    key = f"{FLAG_PREFIX}{name.upper()}"
    val = os.environ.get(key)
    if val is None:
        return None
    return val.strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_enabled(name: str) -> bool:
    """Return whether feature *name* is enabled.

    Resolution order:
    1. Environment variable ``EVOLVER_FF_<NAME>`` (highest priority).
    2. Disk file ``evolver/.config/disk_flags.json``.
    3. Default from :data:`DEFAULT_FLAGS` (lowest priority).
    """
    # 1. Env
    env_val = _env_flag_value(name)
    if env_val is not None:
        return env_val

    # 2. Disk
    disk = _load_disk_flags()
    if name in disk:
        return disk[name]

    # 3. Default
    return DEFAULT_FLAGS.get(name, False)


def get_all_flags() -> dict[str, bool]:
    """Return merged flags (env + disk + default)."""
    merged = dict(DEFAULT_FLAGS)
    merged.update(_load_disk_flags())
    for name in list(merged):
        env_val = _env_flag_value(name)
        if env_val is not None:
            merged[name] = env_val
    return merged


def set_flag(name: str, value: bool, persist: bool = True) -> None:
    """Enable/disable a feature flag.

    If *persist* is ``True`` (default), writes to disk.
    Does **not** modify environment variables.
    """
    global _disk_flags, _disk_flags_loaded_at
    if persist:
        disk = _load_disk_flags(force=True)
        disk[name] = value
        _write_disk_flags(disk)
        with _lock:
            _disk_flags = disk
            _disk_flags_loaded_at = time.monotonic()
    else:
        with _lock:
            _disk_flags[name] = value
            _disk_flags_loaded_at = time.monotonic()


def reset_to_defaults() -> None:
    """Reset disk flags to default set."""
    global _disk_flags, _disk_flags_loaded_at
    _write_disk_flags(DEFAULT_FLAGS)
    with _lock:
        _disk_flags = DEFAULT_FLAGS.copy()
        _disk_flags_loaded_at = time.monotonic()
