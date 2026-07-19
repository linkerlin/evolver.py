"""System health observer — disk, memory, process count, secrets scanning."""

from __future__ import annotations

import dataclasses
from typing import Any


def health_check() -> dict[str, Any]:
    """Run all system health checks and return a structured report."""
    try:
        from evolver.ops.health_check import run_health_check

        report = run_health_check()
        return dataclasses.asdict(report) if report else {}
    except Exception:
        return {"status": "error", "error": "health check failed"}


def health_summary() -> dict[str, Any]:
    """Lightweight health summary for dashboard card."""
    data = health_check()
    checks = data.get("checks", [])
    ok = sum(1 for c in checks if c.get("ok"))
    warn = sum(1 for c in checks if c.get("severity") == "warning")
    crit = sum(1 for c in checks if c.get("severity") == "critical")
    return {
        "status": data.get("status", "unknown"),
        "total": len(checks),
        "ok": ok,
        "warning": warn,
        "critical": crit,
        "timestamp": data.get("timestamp"),
    }
