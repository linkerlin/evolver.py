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
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FLAG_PREFIX = "EVOLVER_FF_"
DISK_FLAG_FILENAME = "disk_flags.json"
DISK_FLAG_DIR = ".config"
DISK_FLAG_TTL = 10.0  # seconds
EVOMAP_FEATURE_FLAGS_PATH_ENV = "EVOMAP_FEATURE_FLAGS_PATH"

# Default flags — shared by GEP cognition and proxy route gating
DEFAULT_FLAGS: dict[str, bool] = {
    "enable_llm_review": True,
    "enable_auto_buyer": False,
    "enable_validator": True,
    "enable_recall_inject": True,
    "enable_reflection": True,
    "enable_auto_distill": True,
    "enable_curriculum": False,
    "enable_explore": False,
    "enable_idle_scheduler": True,
    "enable_local_state_awareness": True,
    "enable_policy_check": True,
    "enable_secret_sanitize": True,
    "enable_memory_graph": True,
    # Proxy-only routes (also readable via ``EVOLVER_FF_*``)
    "enable_skill_auto_update": False,
    "enable_trace_upload": False,
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


def _legacy_evomap_flag_path() -> Path | None:
    """Optional legacy Hub flags file (``~/.evomap/feature_flags.json``)."""
    env = os.environ.get(EVOMAP_FEATURE_FLAGS_PATH_ENV)
    if env:
        return Path(env)
    legacy = Path.home() / ".evomap" / "feature_flags.json"
    return legacy if legacy.exists() else None


def _read_flags_json(path: Path) -> dict[str, bool]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return {
                k: bool(v) for k, v in raw.items() if isinstance(v, (bool, int))
            }
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[FeatureFlags] Failed to read %s: %s", path, exc)
    return {}


def _load_disk_flags(force: bool = False) -> dict[str, bool]:
    """Read workspace + legacy disk flag overlays; seed workspace file if absent."""
    global _disk_flags, _disk_flags_mtime, _disk_flags_loaded_at

    path = _disk_flag_path()
    legacy_path = _legacy_evomap_flag_path()
    now = time.monotonic()

    with _lock:
        if not force and (now - _disk_flags_loaded_at) < DISK_FLAG_TTL:
            return _disk_flags.copy()

        if not path.exists():
            _get_config_dir().mkdir(parents=True, exist_ok=True)
            _write_disk_flags(DEFAULT_FLAGS)

        try:
            mtime = path.stat().st_mtime if path.exists() else 0.0
            legacy_mtime = legacy_path.stat().st_mtime if legacy_path else 0.0
            combined_mtime = max(mtime, legacy_mtime)
            if (
                not force
                and combined_mtime == _disk_flags_mtime
                and (now - _disk_flags_loaded_at) < DISK_FLAG_TTL
            ):
                return _disk_flags.copy()

            merged: dict[str, bool] = {}
            if path.exists():
                merged.update(_read_flags_json(path))
            if legacy_path is not None:
                merged.update(_read_flags_json(legacy_path))
            _disk_flags = merged
            _disk_flags_mtime = combined_mtime
            _disk_flags_loaded_at = now
            return _disk_flags.copy()
        except OSError as exc:
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
    global _disk_flags, _disk_flags_loaded_at, _disk_flags_mtime
    _write_disk_flags(DEFAULT_FLAGS)
    with _lock:
        _disk_flags = DEFAULT_FLAGS.copy()
        _disk_flags_mtime = 0.0
        _disk_flags_loaded_at = time.monotonic()


def invalidate_cache() -> None:
    """Force next read to reload disk flags (tests / hot reload)."""
    global _disk_flags_loaded_at
    with _lock:
        _disk_flags_loaded_at = 0.0
