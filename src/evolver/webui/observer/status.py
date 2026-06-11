"""System health status aggregation for WebUI."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def system_status(memory_dir: Path | None = None) -> dict[str, Any]:
    """Return a summary of system health."""
    from evolver.gep.paths import get_memory_dir

    mem = memory_dir or get_memory_dir()
    status: dict[str, Any] = {"timestamp": time.time(), "components": {}}

    # Event stream health
    events_path = mem / "events.jsonl"
    if events_path.exists():
        size = events_path.stat().st_size
        status["components"]["events"] = {"exists": True, "size_bytes": size}
    else:
        status["components"]["events"] = {"exists": False}

    # Gene / capsule counts
    try:
        import json

        genes = (
            json.loads((mem / "genes.json").read_text(encoding="utf-8"))
            if (mem / "genes.json").exists()
            else {}
        )
        capsules = (
            json.loads((mem / "capsules.json").read_text(encoding="utf-8"))
            if (mem / "capsules.json").exists()
            else {}
        )
        status["components"]["genes"] = {"count": len(genes.get("genes", []))}
        status["components"]["capsules"] = {"count": len(capsules.get("capsules", []))}
    except Exception as exc:
        logger.warning("[Status] Failed to read gene/capsule counts: %s", exc)
        status["components"]["genes"] = {"count": 0, "error": str(exc)}
        status["components"]["capsules"] = {"count": 0, "error": str(exc)}

    # Proxy status (best-effort)
    status["components"]["proxy"] = {"running": _proxy_alive()}

    # Overall
    errors = sum(1 for c in status["components"].values() if c.get("error"))
    status["overall"] = "critical" if errors > 1 else "healthy" if errors == 0 else "warning"
    return status


def _proxy_alive() -> bool:
    """Best-effort check if the local proxy is accepting connections."""
    try:
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(("127.0.0.1", 19820))
        sock.close()
        return True
    except Exception:
        return False
