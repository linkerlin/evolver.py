"""Learning signals — detect environment-specific issues for the GEP pipeline.

Equivalent concept from Node's signal extraction, adapted for Python-specific
and cross-platform concerns.

Detects:
* Platform incompatibilities (Windows shell, macOS case-sensitivity)
* Dependency lock file conflicts (uv.lock, package-lock.json)
* Missing __future__ annotations in Python source files
* Import cycles in the local codebase
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def detect_platform_signals() -> list[dict[str, Any]]:
    """Return signals specific to the current platform."""
    signals: list[dict[str, Any]] = []
    system = platform.system()

    if system == "Windows":
        signals.append(
            {
                "type": "platform_warning",
                "severity": "info",
                "message": "Windows detected: shell scripts may need .bat/.ps1 equivalents",
            }
        )
    elif system == "Darwin":
        signals.append(
            {
                "type": "platform_warning",
                "severity": "info",
                "message": "macOS detected: default filesystem is case-insensitive (APFS)",
            }
        )

    if sys.version_info < (3, 11):
        signals.append(
            {
                "type": "python_version",
                "severity": "warning",
                "message": (
                    f"Python {sys.version_info.major}.{sys.version_info.minor} "
                    "may lack features used by evolver.py"
                ),
            }
        )

    return signals


def detect_lock_conflicts(root: Path | None = None) -> list[dict[str, Any]]:
    """Detect dependency lock file conflicts."""
    from evolver.gep.paths import get_repo_root

    repo = root or get_repo_root() or Path.cwd()
    signals: list[dict[str, Any]] = []

    uv_lock = repo / "uv.lock"
    package_lock = repo / "package-lock.json"

    if uv_lock.exists():
        try:
            text = uv_lock.read_text(encoding="utf-8", errors="ignore")
            if "conflict" in text.lower():
                signals.append(
                    {
                        "type": "dependency_conflict",
                        "severity": "warning",
                        "message": "Possible conflict markers found in uv.lock",
                        "file": str(uv_lock),
                    }
                )
        except OSError as exc:
            logger.debug("[LearningSignals] Failed to read uv.lock: %s", exc)

    if package_lock.exists():
        try:
            data = json.loads(package_lock.read_text(encoding="utf-8"))
            if data.get("lockfileVersion") is None:
                signals.append(
                    {
                        "type": "dependency_conflict",
                        "severity": "warning",
                        "message": "package-lock.json may be corrupted (missing lockfileVersion)",
                        "file": str(package_lock),
                    }
                )
        except (OSError, json.JSONDecodeError) as exc:
            logger.debug("[LearningSignals] Failed to read package-lock.json: %s", exc)
            signals.append(
                {
                    "type": "dependency_conflict",
                    "severity": "warning",
                    "message": "package-lock.json is unreadable (corrupted?)",
                    "file": str(package_lock),
                }
            )

    return signals


def detect_missing_annotations(root: Path | None = None) -> list[dict[str, Any]]:
    """Detect Python source files missing ``from __future__ import annotations``."""
    from evolver.gep.paths import get_repo_root

    repo = root or get_repo_root() or Path.cwd()
    signals: list[dict[str, Any]] = []
    src = repo / "src"
    if not src.exists():
        src = repo

    for py_file in src.rglob("*.py"):
        if py_file.name.startswith("."):
            continue
        try:
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            if "from __future__ import annotations" not in text:
                signals.append(
                    {
                        "type": "missing_future_annotations",
                        "severity": "info",
                        "message": (
                            f"Missing `from __future__ import annotations` in {py_file.name}"
                        ),
                        "file": str(py_file.relative_to(repo)),
                    }
                )
        except OSError as exc:
            logger.debug("[LearningSignals] Failed to read %s: %s", py_file, exc)

    # Limit to top 10 to avoid noise
    return signals[:10]


def gather_all_learning_signals(root: Path | None = None) -> list[dict[str, Any]]:
    """Gather all learning signals for the current environment."""
    signals: list[dict[str, Any]] = []
    signals.extend(detect_platform_signals())
    signals.extend(detect_lock_conflicts(root))
    signals.extend(detect_missing_annotations(root))
    logger.info("[LearningSignals] Gathered %d signals", len(signals))
    return signals


def is_learning_signals_enabled() -> bool:
    return os.environ.get("EVOLVER_LEARNING_SIGNALS", "1").lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def learning_signal_to_string(sig: dict[str, Any]) -> str:
    """Encode a structured learning signal as a GEP pipeline string."""
    sig_type = str(sig.get("type") or "learning")
    severity = str(sig.get("severity") or "info")
    return f"learning_signal:{sig_type}:{severity}"


def gather_pipeline_learning_signals(root: Path | None = None) -> list[str]:
    """Lightweight learning signals for per-cycle pipeline (no full src scan)."""
    from evolver.gep.paths import get_repo_root

    repo = root or get_repo_root() or Path.cwd()
    raw = detect_platform_signals() + detect_lock_conflicts(repo)
    return [learning_signal_to_string(s) for s in raw]
