"""System health checks — disk, memory, process count, secrets.

Equivalent to ``evolver/src/ops/health_check.js``.
Provides a structured ``HealthReport`` with per-check detail.

Design notes (Pythonic)
-----------------------
* Uses **psutil** for memory and process-count queries instead of parsing
  ``/proc`` directly — one cross-platform API.
* Uses **shutil.disk_usage** for disk space (available since Python 3.3).
* Process-count results are cached for 60 s to avoid heavy iteration.
* Every check carries its own ``severity`` so callers can decide whether
  to abort (critical) or merely warn.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    ok: bool
    status: str
    severity: str = "info"  # info | warning | critical


@dataclass
class HealthReport:
    status: str  # ok | warning | error
    timestamp: str
    checks: list[CheckResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _default_mount() -> Path:
    if __import__("platform").system() == "Windows":
        return Path(Path.cwd().anchor)
    return Path("/")


# Simple time-based cache for process count (avoids iterating all PIDs every tick).
_proc_cache: tuple[float, int] | None = None
_PROC_CACHE_TTL_S: float = 60.0


def _get_process_count() -> int | None:
    """Return the number of running processes, or *None* if unavailable."""
    global _proc_cache
    now = time.time()
    if _proc_cache is not None:
        cached_at, cached_val = _proc_cache
        if now - cached_at < _PROC_CACHE_TTL_S:
            return cached_val

    try:
        count = len(psutil.pids())
    except (OSError, psutil.Error):
        return None

    _proc_cache = (now, count)
    return count


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_health_check(
    *,
    mount: Path | str | None = None,
    disk_critical_pct: int = 90,
    disk_warning_pct: int = 80,
    mem_critical_pct: int = 95,
    proc_warning_threshold: int = 2000,
    optional_secrets: list[str] | None = None,
) -> HealthReport:
    """Run the full health-check suite and return a structured report.

    Parameters mirror the thresholds used by the Node.js original so that
    behaviour is equivalent across platforms.
    """
    checks: list[CheckResult] = []
    critical_errors = 0
    warnings = 0

    # 1. Optional secrets presence (informational)
    secrets = optional_secrets or ["OPENAI_API_KEY"]
    for key in secrets:
        value = __import__("os").environ.get(key, "").strip()
        if not value:
            checks.append(
                CheckResult(
                    name=f"env:{key}",
                    ok=False,
                    status="missing",
                    severity="info",
                )
            )
        else:
            checks.append(
                CheckResult(
                    name=f"env:{key}",
                    ok=True,
                    status="present",
                )
            )

    # 2. Disk space
    target = Path(mount) if mount else _default_mount()
    try:
        usage = shutil.disk_usage(target)
        pct = round((usage.used / usage.total) * 100)
        if pct > disk_critical_pct:
            checks.append(
                CheckResult(
                    name="disk_space",
                    ok=False,
                    status=f"{pct}% used",
                    severity="critical",
                )
            )
            critical_errors += 1
        elif pct > disk_warning_pct:
            checks.append(
                CheckResult(
                    name="disk_space",
                    ok=False,
                    status=f"{pct}% used",
                    severity="warning",
                )
            )
            warnings += 1
        else:
            checks.append(
                CheckResult(
                    name="disk_space",
                    ok=True,
                    status=f"{pct}% used",
                )
            )
    except OSError as exc:
        checks.append(
            CheckResult(
                name="disk_space",
                ok=False,
                status=f"check failed: {exc}",
                severity="warning",
            )
        )
        warnings += 1

    # 3. Memory usage
    try:
        mem = psutil.virtual_memory()
        mem_pct = mem.percent
        if mem_pct > mem_critical_pct:
            checks.append(
                CheckResult(
                    name="memory",
                    ok=False,
                    status=f"{mem_pct:.0f}% used",
                    severity="critical",
                )
            )
            critical_errors += 1
        else:
            checks.append(
                CheckResult(
                    name="memory",
                    ok=True,
                    status=f"{mem_pct:.0f}% used",
                )
            )
    except (OSError, psutil.Error) as exc:
        checks.append(
            CheckResult(
                name="memory",
                ok=False,
                status=f"check failed: {exc}",
                severity="warning",
            )
        )
        warnings += 1

    # 4. Process count (fork-bomb / leak detection)
    proc_count = _get_process_count()
    if proc_count is not None:
        if proc_count > proc_warning_threshold:
            checks.append(
                CheckResult(
                    name="process_count",
                    ok=False,
                    status=f"{proc_count} procs",
                    severity="warning",
                )
            )
            warnings += 1
        else:
            checks.append(
                CheckResult(
                    name="process_count",
                    ok=True,
                    status=f"{proc_count} procs",
                )
            )

    # Launcher (uv / uvx / python)
    try:
        from evolver.uv_runtime import describe_launcher

        info = describe_launcher()
        uv_path = info.get("uv")
        uvx_path = info.get("uvx")
        checks.append(
            CheckResult(
                name="launcher",
                ok=True,
                status=(
                    f"mode={info.get('launcher')} "
                    f"uv={'yes' if uv_path else 'no'} "
                    f"uvx={'yes' if uvx_path else 'no'} "
                    f"loop={info.get('resolved_loop')}"
                ),
                severity="info",
            )
        )
    except Exception as exc:
        checks.append(
            CheckResult(
                name="launcher",
                ok=True,
                status=f"unavailable: {exc}",
                severity="info",
            )
        )

    # Overall status
    if critical_errors > 0:
        overall = "error"
    elif warnings > 0:
        overall = "warning"
    else:
        overall = "ok"

    return HealthReport(
        status=overall,
        timestamp=__import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        checks=checks,
    )
