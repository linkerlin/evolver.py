"""Idle-aware scheduler — adjusts evolution intensity based on user activity.

Equivalent to ``evolver/src/gep/idleScheduler.js`` (373 lines).

Monitors user activity (keyboard, mouse) via platform-specific back-ends.
When the user is active, evolution throttles to ``signal_only`` mode; when
idle, it escalates to ``light`` → ``normal`` → ``deep`` over time.

Platform support:
  - **Windows**: ``ctypes`` → ``GetLastInputInfo``.
  - **Linux**: ``xprintidle`` → ``/dev/input`` stat fallback → FS mtime fallback.
  - **macOS**: ``ioreg`` → ``HIDIdleTime``.

Additional features (Node v1.87.4 / ``idleSchedulerLinuxFallbacks.test.js``):
  - ``EVOLVER_IDLE_OVERRIDE`` env to force a specific intensity.
  - Build/compile activity detection (recent file mtime in memory/ or build
    dirs counts as active — prevents misjudging long compiles as idle).
  - FS-only idle fallback: when no platform idle source is available, infer
    activity from the mtime of recent files in the memory/ directory.
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import subprocess
import time
from contextlib import suppress
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INTENSITY_LIGHT_THRESHOLD = 60  # seconds idle to trigger light
INTENSITY_NORMAL_THRESHOLD = 300  # seconds idle to trigger normal
INTENSITY_DEEP_THRESHOLD = 900  # seconds idle to trigger deep

#: If a file in these directories was modified within this window, treat the
#: user as active (build/compile detection).
_BUILD_ACTIVITY_WINDOW_S = 120
_BUILD_ACTIVITY_DIRS = ("memory", ".evolver", "logs", "dist", "build", ".pytest_cache")

# ---------------------------------------------------------------------------
# Intensity enum
# ---------------------------------------------------------------------------


class EvolutionIntensity(str, Enum):  # noqa: UP042
    signal_only = "signal_only"
    light = "light"
    normal = "normal"
    deep = "deep"


# ---------------------------------------------------------------------------
# Platform-specific idle time
# ---------------------------------------------------------------------------


def _idle_time_windows() -> float:
    """Return milliseconds since last input event on Windows."""

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_ulong)]

    user32 = ctypes.windll.user32
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if user32.GetLastInputInfo(ctypes.byref(lii)):
        return float((ctypes.windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0)
    return 0.0


def _idle_time_linux() -> float:
    """Best-effort Linux idle time via X11 or /dev/input."""
    # Try X11 idle via xprintidle
    try:
        result = subprocess.run(
            ["xprintidle"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            return int(result.stdout.strip()) / 1000.0
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass

    # Fallback: scan /dev/input for recent events (requires root)
    try:
        newest = 0.0
        for dev in os.listdir("/dev/input"):
            if dev.startswith("event"):
                try:
                    st = os.stat(f"/dev/input/{dev}")
                    newest = max(newest, st.st_atime)
                except OSError:
                    pass
        if newest:
            return time.time() - newest
    except OSError:
        pass

    # Final fallback: assume active
    return 0.0


def _idle_time_macos() -> float:
    """Best-effort macOS idle time via ioreg."""
    try:
        result = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        for line in result.stdout.splitlines():
            if "HIDIdleTime" in line:
                parts = line.split("=")
                if len(parts) == 2:
                    val = parts[1].strip()
                    try:
                        ns = int(val)
                        if ns > 2**63:  # unsigned wrap
                            ns -= 2**64
                        return abs(ns) / 1e9
                    except ValueError:
                        pass
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError):
        pass
    return 0.0


def _detect_build_activity() -> bool:
    """Return True if recent build/compile activity is detected.

    Checks the mtime of files in known build/memory directories — if any
    was modified within ``_BUILD_ACTIVITY_WINDOW_S``, the user is likely
    running a build (not truly idle).
    """
    now = time.time()
    try:
        from evolver.gep.paths import get_workspace_root  # noqa: PLC0415

        root = get_workspace_root()
    except Exception:
        root = Path.cwd()
    for dirname in _BUILD_ACTIVITY_DIRS:
        dirpath = root / dirname
        if not dirpath.is_dir():
            continue
        try:
            for entry in dirpath.iterdir():
                if now - entry.stat().st_mtime < _BUILD_ACTIVITY_WINDOW_S:
                    return True
        except OSError:
            continue
    return False


def _fs_idle_fallback() -> float:
    """FS-only idle estimation when no platform idle source is available.

    Infers activity from the mtime of the most recent file in ``memory/`` —
    if nothing was written recently, the user is likely idle.
    """
    try:
        from evolver.gep.paths import get_memory_dir  # noqa: PLC0415

        memory_dir = get_memory_dir()
    except Exception:
        return 0.0
    if not memory_dir.is_dir():
        return 0.0
    newest_mtime = 0.0
    try:
        for entry in memory_dir.rglob("*"):
            if entry.is_file():
                mtime = entry.stat().st_mtime
                newest_mtime = max(newest_mtime, mtime)
    except OSError:
        pass
    if newest_mtime == 0.0:
        return 0.0
    return max(0.0, time.time() - newest_mtime)


def _idle_time() -> float:
    """Return seconds since last user input (best-effort, cross-platform)."""
    system = platform.system()
    if system == "Windows":
        return _idle_time_windows()
    if system == "Linux":
        idle = _idle_time_linux()
        if idle > 0:
            return idle
        return _fs_idle_fallback()
    if system == "Darwin":
        idle = _idle_time_macos()
        if idle > 0:
            return idle
        return _fs_idle_fallback()
    logger.warning("[IdleScheduler] Unknown platform %r — assuming active", system)
    return 0.0


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def get_intensity() -> EvolutionIntensity:
    """Return the current evolution intensity based on idle time.

    Honors ``EVOLVER_IDLE_OVERRIDE`` (one of the intensity level names) and
    suppresses deep evolution during detected build/compile activity.
    """
    override = os.environ.get("EVOLVER_IDLE_OVERRIDE", "").strip().lower()
    if override:
        for level in EvolutionIntensity:
            if level.value == override:
                return level

    # Build/compile activity detection: treat as active (signal_only).
    if _detect_build_activity():
        return EvolutionIntensity.signal_only

    idle = _idle_time()
    return intensity_for_duration(idle)


def should_mutate() -> bool:
    """Return ``True`` if mutation is allowed at current intensity."""
    return get_intensity() != EvolutionIntensity.signal_only


def intensity_for_duration(idle_seconds: float) -> EvolutionIntensity:
    """Map an idle duration to an intensity level (deterministic, testable)."""
    if idle_seconds >= INTENSITY_DEEP_THRESHOLD:
        return EvolutionIntensity.deep
    if idle_seconds >= INTENSITY_NORMAL_THRESHOLD:
        return EvolutionIntensity.normal
    if idle_seconds >= INTENSITY_LIGHT_THRESHOLD:
        return EvolutionIntensity.light
    return EvolutionIntensity.signal_only


# ---------------------------------------------------------------------------
# Notification (cross-platform, best-effort)
# ---------------------------------------------------------------------------


def notify(title: str, message: str) -> None:
    """Show a desktop notification if possible (best-effort, never raises)."""
    system = platform.system()
    if system == "Windows":
        with suppress(Exception):
            from ctypes import windll  # noqa: PLC0415

            windll.user32.MessageBoxW(0, message, title, 0x40 | 0x0)
    elif system == "Darwin":
        with suppress(Exception):
            subprocess.run(
                ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
                capture_output=True,
                timeout=5,
                check=False,
            )
    else:
        with suppress(Exception):
            subprocess.run(
                ["notify-send", title, message],
                capture_output=True,
                timeout=5,
                check=False,
            )
