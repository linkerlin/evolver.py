"""Cycle hard-timeout, progress heartbeat, and daemon respawn helpers.

Ports Node ``index.js`` helpers for Issue #19 (hard timeout) and #528
(Windows suicide-respawn policy):

* :class:`CycleTimeoutError` — structured timeout with ``code=CYCLE_TIMEOUT``
* :func:`write_cycle_progress_atomic` — tmp+rename progress file
* :func:`spawn_replacement_process` — Windows skips detached spawn by default
* :func:`handle_cycle_timeout` — continue vs respawn policy (``EVOLVER_SUICIDE``)
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CYCLE_TIMEOUT_MS = 2_700_000  # 45 minutes
DEFAULT_PROGRESS_UPDATE_MS = 60_000


class CycleTimeoutError(TimeoutError):
    """Raised when a single evolution cycle exceeds the hard timeout."""

    def __init__(self, timeout_ms: int, phase: str, cycle_num: int) -> None:
        message = (
            f"Cycle hard-timeout exceeded after {timeout_ms}ms (cycle={cycle_num}, phase={phase})"
        )
        super().__init__(message)
        self.name = "CycleTimeoutError"
        self.code = "CYCLE_TIMEOUT"
        self.timeout_ms = timeout_ms
        self.phase = phase
        self.cycle_num = cycle_num


def parse_bool_env(value: str | None, fallback: bool) -> bool:
    """Parse common truthy/falsy env strings; unknown → *fallback*."""
    if value is None:
        return fallback
    s = str(value).lower().strip()
    if s == "":
        return fallback
    if s in ("false", "0", "off", "no"):
        return False
    if s in ("true", "1", "on", "yes"):
        return True
    return fallback


def parse_ms_env(value: str | None, fallback: int) -> int:
    """Parse a positive millisecond env int; invalid → *fallback*."""
    if value is None or str(value).strip() == "":
        return fallback
    try:
        n = int(str(value).strip())
    except ValueError:
        return fallback
    return n if n > 0 else fallback


def cycle_timeout_enabled() -> bool:
    return parse_bool_env(os.environ.get("EVOLVER_CYCLE_TIMEOUT_ENABLED"), True)


def cycle_timeout_ms() -> int:
    return parse_ms_env(os.environ.get("EVOLVER_CYCLE_TIMEOUT_MS"), DEFAULT_CYCLE_TIMEOUT_MS)


def progress_update_ms() -> int:
    return parse_ms_env(os.environ.get("EVOLVER_PROGRESS_UPDATE_MS"), DEFAULT_PROGRESS_UPDATE_MS)


def suicide_enabled() -> bool:
    """Whether timeout/max-cycles should respawn (``EVOLVER_SUICIDE``, default true)."""
    return parse_bool_env(os.environ.get("EVOLVER_SUICIDE"), True)


def write_cycle_progress_atomic(
    progress_path: Path | str,
    fields: dict[str, Any],
) -> bool:
    """Atomically write cycle_progress.json (tmp+rename). Returns False on error."""
    path = Path(progress_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {**fields, "updated_at": int(time.time() * 1000)}
        tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        # Ensure no other .tmp.<pid> leftovers from this write.
        return True
    except OSError:
        return False


def spawn_replacement_process(
    *,
    reason: str,
    args: list[str] | None = None,
    log_path: Path | str | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    """Spawn a replacement daemon process (or skip on Windows by default).

    Returns ``{spawned, reason?, error?}``. On Windows without
    ``EVOLVER_SUICIDE_WINDOWS=true``, returns ``windows_default_skip`` so an
    external supervisor can restart on exit code 1 (Issue #528).
    """
    is_windows = (platform or sys.platform).startswith("win")
    allow_on_windows = parse_bool_env(os.environ.get("EVOLVER_SUICIDE_WINDOWS"), False)
    if is_windows and not allow_on_windows:
        logger.info(
            "[Daemon] Skipping in-process respawn on Windows (%s). "
            "Set EVOLVER_SUICIDE_WINDOWS=true to opt in. "
            "Recommended: external supervisor (NSSM, pm2-windows, etc.).",
            reason,
        )
        return {"spawned": False, "reason": "windows_default_skip"}

    argv = list(args or ["--loop"])
    log = Path(log_path) if log_path else Path("evolver-daemon.log")
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        log_handle = open(log, "a", encoding="utf-8")
    except OSError as exc:
        logger.error("[Daemon] Spawn-replacement failed (%s): %s", reason, exc)
        return {"spawned": False, "reason": "spawn_error", "error": exc}

    try:
        # Detached-ish: new process group on POSIX; Windows uses CREATE_NO_WINDOW when possible.
        creationflags = 0
        if is_windows:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
                subprocess, "DETACHED_PROCESS", 0
            )
        # Prefer re-invoking the current entrypoint module.
        cmd = [sys.executable, "-m", "evolver", *argv]
        kwargs: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": log_handle,
            "stderr": log_handle,
            "env": os.environ.copy(),
            "close_fds": not is_windows,
        }
        if is_windows:
            kwargs["creationflags"] = creationflags
        else:
            kwargs["start_new_session"] = True
        child = subprocess.Popen(cmd, **kwargs)
        # Parent no longer owns the log fd exclusively after spawn.
        with contextlib.suppress(OSError):
            log_handle.close()
        if hasattr(child, "pid"):
            logger.info("[Daemon] Spawned replacement pid=%s reason=%s", child.pid, reason)
        return {"spawned": True, "pid": getattr(child, "pid", None)}
    except Exception as exc:
        with contextlib.suppress(OSError):
            log_handle.close()
        logger.error("[Daemon] Spawn-replacement failed (%s): %s", reason, exc)
        return {"spawned": False, "reason": "spawn_error", "error": exc}


def handle_cycle_timeout(
    *,
    error: BaseException,
    cycle_progress_path: Path | str,
    progress_fields: dict[str, Any],
    suicide_enabled_flag: bool | None = None,
    args: list[str] | None = None,
    log_path: Path | str | None = None,
    spawn_replacement_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Decide continue vs respawn after a hard cycle timeout.

    Returns ``{"action": "continue"|"respawn"}``.
    """
    msg = str(getattr(error, "message", None) or error)
    logger.error("[Daemon] %s", msg)
    print(f"[Daemon] {msg}", file=sys.stderr)

    enabled = suicide_enabled() if suicide_enabled_flag is None else suicide_enabled_flag
    if not enabled:
        print(
            "[Daemon] Cycle hard-timeout treated as non-fatal because EVOLVER_SUICIDE=false.",
            file=sys.stderr,
        )
        write_cycle_progress_atomic(
            cycle_progress_path,
            {**progress_fields, "phase": "cycle_timeout_nonfatal"},
        )
        return {"action": "continue"}

    write_cycle_progress_atomic(
        cycle_progress_path,
        {**progress_fields, "phase": "cycle_timeout_respawn"},
    )
    spawner = spawn_replacement_fn or spawn_replacement_process
    spawner(
        reason="cycle_hard_timeout",
        args=args or ["--loop"],
        log_path=log_path,
    )
    return {"action": "respawn"}


async def wait_for_timed_out_task(task: Any, log_fn: Callable[[str], None] | None = None) -> None:
    """Await a timed-out cycle task so the next cycle does not overlap."""
    try:
        await task
    except Exception as exc:
        msg = f"[Daemon] Timed-out evolve.run() eventually rejected: {exc}"
        if log_fn is not None:
            log_fn(msg)
        else:
            logger.error(msg)


__all__ = [
    "DEFAULT_CYCLE_TIMEOUT_MS",
    "DEFAULT_PROGRESS_UPDATE_MS",
    "CycleTimeoutError",
    "cycle_timeout_enabled",
    "cycle_timeout_ms",
    "handle_cycle_timeout",
    "parse_bool_env",
    "parse_ms_env",
    "progress_update_ms",
    "spawn_replacement_process",
    "suicide_enabled",
    "wait_for_timed_out_task",
    "write_cycle_progress_atomic",
]
