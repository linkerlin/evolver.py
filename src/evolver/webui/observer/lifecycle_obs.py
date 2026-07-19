"""Daemon lifecycle observer — status, health, uptime, restart counts."""

from __future__ import annotations

from typing import Any


def lifecycle_status() -> dict[str, Any]:
    """Return daemon status (running PIDs, state, proxy health)."""
    try:
        from evolver.ops.lifecycle import check_health, check_proxy_health, status

        st = status()
        h = check_health()
        proxy = check_proxy_health()

        return {
            "running": st.running,
            "processes": [{"pid": p.pid, "cmdline": p.cmdline} for p in st.processes],
            "log_file": st.log_file,
            "healthy": h.healthy,
            "reason": h.reason,
            "pids": h.pids,
            "silence_minutes": h.silence_minutes,
            "proxy_healthy": proxy.get("healthy", False),
            "proxy_port": proxy.get("port"),
        }
    except Exception:
        return {"running": False, "error": "lifecycle query failed"}


def lifecycle_summary() -> dict[str, Any]:
    """Compact lifecycle summary for dashboard card."""
    data = lifecycle_status()
    pids = data.get("pids", [])
    return {
        "running": data.get("running", False),
        "pid_count": len(pids) if pids else 0,
        "healthy": data.get("healthy", False),
        "proxy_healthy": data.get("proxy_healthy", False),
        "silence_minutes": data.get("silence_minutes"),
    }
