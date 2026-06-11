"""Trace controller: dynamically adjust logging and tracing scope.

Equivalent to evolver/src/proxy/extensions/traceControl.js.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from evolver.config import resolve_hub_url
from evolver.gep.a2a_protocol import build_hub_headers
from evolver.proxy.router.features import is_route_enabled


class TraceControl:
    """Control debug logging and generate trace reports."""

    def __init__(self, trace_dir: Path | None = None) -> None:
        self.trace_dir = trace_dir or (Path.home() / ".evomap" / "traces")
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self._enabled_modules: set[str] = set()
        self._global_level: str = "info"

    def enable_module(self, module: str, level: str = "debug") -> dict[str, Any]:
        """Enable debug tracing for a specific module."""
        self._enabled_modules.add(module)
        return {"ok": True, "module": module, "level": level}

    def disable_module(self, module: str) -> dict[str, Any]:
        """Disable debug tracing for a module."""
        self._enabled_modules.discard(module)
        return {"ok": True, "module": module, "level": "info"}

    def set_global_level(self, level: str) -> dict[str, Any]:
        """Set the global log level."""
        self._global_level = level
        return {"ok": True, "global_level": level}

    def get_status(self) -> dict[str, Any]:
        """Return current trace status."""
        return {
            "global_level": self._global_level,
            "enabled_modules": sorted(self._enabled_modules),
        }

    def generate_report(self, duration_seconds: int = 300) -> dict[str, Any]:
        """Generate a trace report from recent log data."""
        report_id = f"trace_{int(time.time())}"
        report = {
            "id": report_id,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "duration_seconds": duration_seconds,
            "modules": sorted(self._enabled_modules),
            "global_level": self._global_level,
        }
        path = self.trace_dir / f"{report_id}.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return {"ok": True, "report_id": report_id, "path": str(path)}

    def upload_report(self, report_id: str) -> dict[str, Any]:
        """Upload a trace report to the Hub."""
        path = self.trace_dir / f"{report_id}.json"
        if not path.exists():
            return {"ok": False, "error": "report_not_found"}

        if not is_route_enabled("trace_upload"):
            return {"ok": False, "error": "feature_disabled", "report_id": report_id}

        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": "read_failed", "detail": str(exc)}

        try:
            hub = resolve_hub_url()
        except ValueError:
            return {"ok": False, "error": "no_hub_url", "report_id": report_id}

        url = f"{hub}/v1/a2a/trace/report"
        payload = {"report_id": report_id, "report": report}

        try:
            with httpx.Client(timeout=30.0, http2=True) as client:
                response = client.post(url, json=payload, headers=build_hub_headers())
                if response.status_code >= 400:
                    return {
                        "ok": False,
                        "error": "upload_failed",
                        "status": response.status_code,
                        "report_id": report_id,
                    }
        except Exception as exc:
            return {
                "ok": False,
                "error": "upload_failed",
                "detail": str(exc),
                "report_id": report_id,
            }

        return {"ok": True, "report_id": report_id, "uploaded": True}


def create_trace_control(trace_dir: Path | None = None) -> TraceControl:
    return TraceControl(trace_dir=trace_dir)


__all__ = ["TraceControl", "create_trace_control"]
