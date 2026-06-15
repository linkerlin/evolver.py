"""Device ID — generate a stable, anonymous hardware fingerprint.

Equivalent to ``evolver/src/gep/deviceId.js``.

Produces a stable device identifier from hardware characteristics (platform,
architecture, CPU count, machine ID). The ID is:
  - **Stable**: same machine yields the same ID across reboots.
  - **Anonymous**: contains no personally identifiable information.
  - **Non-reversible**: hashed with SHA-256.
"""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import uuid


def _collect_hardware_signals() -> list[str]:
    """Collect hardware signals for fingerprinting."""
    signals = [
        platform.system(),
        platform.machine(),
        platform.processor(),
        str(os.cpu_count() or 0),
    ]

    # MAC address (first interface) — stable across reboots, not PII.
    try:
        mac = uuid.getnode()
        signals.append(f"mac:{mac:012x}")
    except Exception:
        pass

    # Machine GUID on Windows.
    if platform.system() == "Windows":
        try:
            import winreg  # type: ignore[import-not-found, unused-ignore]  # noqa: PLC0415

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\\Microsoft\\Cryptography",
            ) as key:
                guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                signals.append(f"win-guid:{guid}")
        except Exception:
            pass

    # /etc/machine-id on Linux.
    if platform.system() == "Linux":
        try:
            mid = open("/etc/machine-id").read().strip()  # noqa: SIM115
            if mid:
                signals.append(f"linux-mid:{mid}")
        except OSError:
            pass

    # IOPlatformUUID on macOS.
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["ioreg", "-d2", "-c", "IOPlatformExpertDevice"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            for line in result.stdout.splitlines():
                if "IOPlatformUUID" in line:
                    uuid_val = line.split("=")[-1].strip().strip('"')
                    signals.append(f"mac-uuid:{uuid_val}")
                    break
        except Exception:
            pass

    return signals


def get_device_id() -> str:
    """Return a stable, anonymous device identifier (16-byte hex)."""
    signals = _collect_hardware_signals()
    raw = "|".join(signals)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def get_device_fingerprint() -> dict[str, str]:
    """Return a dict with the device ID and platform info (for display)."""
    return {
        "device_id": get_device_id(),
        "platform": platform.system(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
    }


__all__ = ["get_device_fingerprint", "get_device_id"]
