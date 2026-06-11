"""Idle-aware scheduler — adjusts evolution intensity based on user activity.

Equivalent to Node's ``evolver/src/gep/idleScheduler.js``.

Monitors user activity (keyboard, mouse) via platform-specific
back-ends. When the user is active, evolution throttles to
``signal_only`` mode; when idle, it escalates to ``light`` →
``normal`` → ``deep`` over time.

Windows: uses ``ctypes`` to call ``GetLastInputInfo``.
Linux: reads ``/dev/input`` or ``X11`` idle time.
macOS: uses ``ioreg`` / ``IOKit`` (not yet implemented).

Intensity levels
----------------
* ``signal_only`` — log signals, no mutation (user is active).
* ``light`` — small, single-file mutations (1 min idle).
* ``normal`` — normal evolution cycle (5 min idle).
* ``deep`` — full evolution with tests (15 min idle).
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import struct
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INTENSITY_LIGHT_THRESHOLD = 60    # seconds idle to trigger light
INTENSITY_NORMAL_THRESHOLD = 300  # seconds idle to trigger normal
INTENSITY_DEEP_THRESHOLD = 900    # seconds idle to trigger deep

# ---------------------------------------------------------------------------
# Intensity enum
# ---------------------------------------------------------------------------


class EvolutionIntensity(str, Enum):
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
        return (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0
    return 0.0


def _idle_time_linux() -> float:
    """Best-effort Linux idle time via X11 or /dev/input."""
    # Try X11 idle via xprintidle
    try:
        import subprocess
        result = subprocess.run(
            ["xprintidle"],
            capture_output=True,
            text=True,
            timeout=2,
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
        import subprocess
        result = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        for line in result.stdout.splitlines():
            if "HIDIdleTime" in line:
                # e.g. "HIDIdleTime" = 18446744073709551615
                parts = line.split("=")
                if len(parts) == 2:
                    val = parts[1].strip()
                    # Handle 64-bit nanoseconds
                    try:
                        ns = int(val)
                        if ns > 2**63:  # unsigned wrap
                            ns -= 2**64
                        return abs(ns) / 1e9
                    except ValueError:
                        pass
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return 0.0


def _idle_time() -> float:
    """Return seconds since last user input (best-effort, cross-platform)."""
    system = platform.system()
    if system == "Windows":
        return _idle_time_windows()
    if system == "Linux":
        return _idle_time_linux()
    if system == "Darwin":
        return _idle_time_macos()
    logger.warning("[IdleScheduler] Unknown platform %r — assuming active", system)
    return 0.0


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def get_intensity() -> EvolutionIntensity:
    """Return the current evolution intensity based on idle time."""
    idle = _idle_time()
    if idle >= INTENSITY_DEEP_THRESHOLD:
        return EvolutionIntensity.deep
    if idle >= INTENSITY_NORMAL_THRESHOLD:
        return EvolutionIntensity.normal
    if idle >= INTENSITY_LIGHT_THRESHOLD:
        return EvolutionIntensity.light
    return EvolutionIntensity.signal_only


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
    """Show a desktop notification if possible."""
    system = platform.system()
    if system == "Windows":
        try:
            from ctypes import windll
            windll.user32.MessageBoxW(0, message, title, 0x40 | 0x0)
        except Exception:
            logger.debug("[IdleScheduler] Windows notification failed")
    elif system == "Darwin":
        try:
            import subprocess
            subprocess.run(
                ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            logger.debug("[IdleScheduler] macOS notification failed")
    else:
        try:
            import subprocess
            subprocess.run(
                ["notify-send", title, message],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            logger.debug("[IdleScheduler] Linux notification failed")
