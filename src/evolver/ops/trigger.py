"""External trigger system: HTTP endpoint and filesystem watcher for evolution cycles.

Equivalent to evolver/src/ops/trigger.js.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from evolver.gep.paths import get_memory_dir

TRIGGER_FILE_NAME = ".trigger"
TRIGGER_HTTP_ENDPOINT = "/trigger"
TRIGGER_COOLDOWN_SECONDS = 5.0

_last_trigger_time: float = 0.0


def _trigger_file_path() -> Path:
    return get_memory_dir() / TRIGGER_FILE_NAME


def check_file_trigger() -> bool:
    """Check if the filesystem trigger file exists.

    Returns True if a trigger is present and has not been consumed.
    """
    path = _trigger_file_path()
    return path.exists()


def consume_file_trigger() -> dict[str, Any] | None:
    """Consume the filesystem trigger file and return its payload.

    Returns None if no trigger file exists.
    """
    path = _trigger_file_path()
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8").strip()
        # Remove the trigger file to prevent re-triggering
        path.unlink()
        payload: dict[str, Any] = {"source": "filesystem", "timestamp": time.time()}
        if content:
            try:
                payload["data"] = __import__("json").loads(content)
            except __import__("json").JSONDecodeError:
                payload["data"] = content
        return payload
    except OSError:
        return None


def create_file_trigger(payload: dict[str, Any] | str | None = None) -> dict[str, Any]:
    """Create a filesystem trigger to fire the next evolution cycle."""
    path = _trigger_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = ""
    if isinstance(payload, dict):
        content = __import__("json").dumps(payload, ensure_ascii=False)
    elif isinstance(payload, str):
        content = payload
    try:
        path.write_text(content + "\n", encoding="utf-8")
        return {"ok": True, "path": str(path)}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}


def check_http_trigger_allowed() -> bool:
    """Check if enough time has passed since the last HTTP trigger."""
    global _last_trigger_time
    return time.time() - _last_trigger_time >= TRIGGER_COOLDOWN_SECONDS


def record_http_trigger(source: str = "unknown") -> dict[str, Any]:
    """Record an HTTP trigger request.

    Returns the trigger payload if allowed, or a cooldown rejection.
    """
    global _last_trigger_time
    now = time.time()
    elapsed = now - _last_trigger_time
    if elapsed < TRIGGER_COOLDOWN_SECONDS:
        return {
            "ok": False,
            "error": "cooldown",
            "cooldown_remaining": round(TRIGGER_COOLDOWN_SECONDS - elapsed, 2),
        }
    _last_trigger_time = now
    return {
        "ok": True,
        "source": source,
        "timestamp": now,
    }


async def wait_for_trigger(
    *,
    timeout: float | None = None,
    check_interval: float = 1.0,
) -> dict[str, Any] | None:
    """Block until a trigger fires (filesystem or internal event).

    Used by the daemon loop to support external trigger mode.
    """
    start = time.time()
    while True:
        payload = consume_file_trigger()
        if payload is not None:
            return payload
        if timeout is not None and time.time() - start >= timeout:
            return None
        await asyncio.sleep(check_interval)


__all__ = [
    "TRIGGER_COOLDOWN_SECONDS",
    "TRIGGER_FILE_NAME",
    "TRIGGER_HTTP_ENDPOINT",
    "check_file_trigger",
    "check_http_trigger_allowed",
    "consume_file_trigger",
    "create_file_trigger",
    "record_http_trigger",
    "wait_for_trigger",
]
