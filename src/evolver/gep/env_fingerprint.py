"""Capture environment fingerprint for reports/issues.

Equivalent to evolver/src/gep/envFingerprint.js.
"""

from __future__ import annotations

import os
import platform
import sys


def capture_env_fingerprint() -> dict[str, str]:
    return {
        "platform": sys.platform,
        "arch": platform.machine() or "unknown",
        "python_version": platform.python_version(),
        "evolver_version": _evolver_version(),
    }


def env_fingerprint_key(env: dict[str, str] | None = None) -> str:
    if env is None:
        env = capture_env_fingerprint()
    parts = [env.get("platform", ""), env.get("arch", ""), env.get("python_version", "")]
    return "/".join(p for p in parts if p) or "unknown"


def detect_model_name() -> str | None:
    return os.environ.get("EVOLVER_MODEL_NAME") or os.environ.get("AGENT_MODEL")


def is_same_env_class(a: dict[str, str], b: dict[str, str]) -> bool:
    return env_fingerprint_key(a) == env_fingerprint_key(b)


def _evolver_version() -> str:
    try:
        from evolver import __version__

        return __version__
    except Exception:
        return "0.0.0"
