"""Evolver lifecycle manager — cross-platform daemon control.

Equivalent to ``evolver/src/ops/lifecycle.js``.
Provides: ``start``, ``stop``, ``restart``, ``status``, ``tail_log``,
``check_health``, ``watch``.

Design notes (Pythonic)
-----------------------
* Process discovery uses **psutil** for a single cross-platform API instead
  of shelling out to ``wmic`` / ``ps``.
* Results are typed with ``@dataclass`` — easy to serialize and test.
* Logging goes through the standard library ``logging`` module; callers
  (e.g. CLI) can opt-in to printing by configuring a handler.
* Detached spawning uses ``subprocess`` flags appropriate for each OS:
  ``CREATE_NEW_PROCESS_GROUP`` on Windows, ``start_new_session`` on Unix.
* The ``watch`` supervisor detects **clock jumps** (macOS sleep / resume)
  by comparing wall-clock time with the monotonic clock.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil

from evolver.config import MAX_SILENCE_MS

# Cross-platform signal constant: Windows lacks SIGKILL.
_SIGKILL = getattr(signal, "SIGKILL", signal.SIGTERM)
from evolver.gep.paths import get_evolver_log_path, get_memory_dir, get_workspace_root

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    cmdline: str


@dataclass
class StartResult:
    status: str  # "started" | "already_running"
    pid: int | None = None


@dataclass
class StopResult:
    status: str  # "stopped" | "not_running"
    killed: list[int] = field(default_factory=list)


@dataclass
class StatusResult:
    running: bool
    processes: list[ProcessInfo] = field(default_factory=list)
    log_file: str | None = None


@dataclass
class TailResult:
    file: str | None = None
    content: str | None = None
    error: str | None = None


@dataclass
class HealthResult:
    healthy: bool
    reason: str | None = None
    pids: list[int] = field(default_factory=list)
    silence_minutes: int | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _pid_file_path() -> Path:
    return get_memory_dir() / "evolver_loop.pid"


def _loop_command() -> Sequence[str]:
    """Return the command line used to spawn the daemon loop.

    External supervisors can override via ``EVOLVER_LOOP_COMMAND``
    (space-separated string). The default is ``sys.executable -m evolver --loop``.
    """
    env = os.environ.get("EVOLVER_LOOP_COMMAND")
    if env:
        return env.split()
    return [sys.executable, "-m", "evolver", "--loop"]


def _is_evolver_loop_process(proc: psutil.Process) -> bool:
    """Return *True* if *proc* looks like an evolver daemon loop.

    We match on the full command line: it must contain both ``"evolver"``
    and ``"--loop"`` (case-insensitive) and must **not** be the current
    process (avoids matching the lifecycle manager itself).
    """
    if proc.pid == os.getpid():
        return False
    try:
        cmdline = " ".join(proc.cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    low = cmdline.lower()
    return "evolver" in low and "--loop" in low


def _list_evolver_processes() -> list[ProcessInfo]:
    """Scan all system processes and return evolver loop matches."""
    found: list[ProcessInfo] = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        if _is_evolver_loop_process(proc):
            try:
                cmd = " ".join(proc.cmdline())
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                cmd = ""
            found.append(ProcessInfo(pid=proc.pid, cmdline=cmd))
    return found


def _is_pid_running(pid: int) -> bool:
    """Send signal 0 to test whether *pid* exists without affecting it."""
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _sleep_ms(ms: float) -> None:
    """Blocking sleep in milliseconds."""
    time.sleep(max(0.0, ms) / 1000.0)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start(*, delay_ms: int = 0) -> StartResult:
    """Start the evolver daemon loop if not already running.

    The child process is spawned **detached** so it survives the parent
    terminal closing. Stdout/stderr are appended to the evolver log file.
    """
    running = _list_evolver_processes()
    if running:
        pids = [p.pid for p in running]
        logger.info("Already running (PIDs: %s).", ", ".join(map(str, pids)))
        return StartResult(status="already_running", pid=pids[0])

    if delay_ms > 0:
        _sleep_ms(delay_ms)

    cmd = _loop_command()
    log_path = get_evolver_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    workspace = get_workspace_root()

    logger.info("Starting: %s (log=%s)", " ".join(cmd), log_path)

    # Open log file in append mode for the child.
    # We use low-level os.open so we can pass the fd directly to Popen.
    with open(log_path, "a", encoding="utf-8") as log_fh:
        popen_kwargs: dict[str, Any] = {
            "args": cmd,
            "stdin": subprocess.DEVNULL,
            "stdout": log_fh.fileno(),
            "stderr": log_fh.fileno(),
            "cwd": str(workspace),
            "env": {**os.environ},
        }

        if platform.system() == "Windows":
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NO_WINDOW
            )
        else:
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen(**popen_kwargs)

    # Record PID for fast-path discovery.
    pid_file = _pid_file_path()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(proc.pid), encoding="utf-8")

    logger.info("Started PID %d", proc.pid)
    return StartResult(status="started", pid=proc.pid)


def stop() -> StopResult:
    """Stop all evolver daemon loop processes.

    Sends ``SIGTERM`` (or ``CTRL_BREAK_EVENT`` on Windows), waits up to
    5 seconds, then force-kills any survivors.
    """
    targets = _list_evolver_processes()
    if not targets:
        logger.info("No running evolver loops found.")
        _unlink_pid_file()
        return StopResult(status="not_running")

    # Phase 1 — gentle termination
    for info in targets:
        logger.info("Stopping PID %d...", info.pid)
        try:
            if platform.system() == "Windows":
                # Ctrl+Break is the Windows equivalent of SIGTERM for process
                # groups created with CREATE_NEW_PROCESS_GROUP.
                os.kill(info.pid, signal.CTRL_BREAK_EVENT)
            else:
                os.kill(info.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass

    # Phase 2 — wait for graceful exit
    for _ in range(10):
        _sleep_ms(500)
        remaining = [p for p in targets if _is_pid_running(p.pid)]
        if not remaining:
            break

    # Phase 3 — force kill survivors
    killed: list[int] = []
    for info in targets:
        if not _is_pid_running(info.pid):
            continue
        logger.warning("Force-killing PID %d", info.pid)
        try:
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(info.pid)],
                    capture_output=True,
                    check=False,
                )
            else:
                os.kill(info.pid, _SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        killed.append(info.pid)

    _unlink_pid_file()
    logger.info("All stopped.")
    return StopResult(status="stopped", killed=[info.pid for info in targets])


def restart(*, delay_ms: int = 2000) -> StartResult:
    """Convenience: stop then start."""
    stop()
    return start(delay_ms=delay_ms)


def status() -> StatusResult:
    """Return current daemon status."""
    running = _list_evolver_processes()
    log_path = get_evolver_log_path()
    log_rel = log_path.name if log_path.exists() else None
    return StatusResult(
        running=bool(running),
        processes=running,
        log_file=log_rel,
    )


def tail_log(lines: int = 20) -> TailResult:
    """Return the last *lines* of the evolver log file.

    Implemented as a pure-Python tail (no external ``tail`` dependency):
    reads backwards in 64 KiB chunks until we have enough lines.
    """
    log_path = get_evolver_log_path()
    if not log_path.exists():
        return TailResult(error="No log file")

    try:
        content = _tail_file(log_path, lines)
    except OSError as exc:
        return TailResult(error=str(exc))

    return TailResult(
        file=log_path.name,
        content=content,
    )


def _tail_file(path: Path, n: int) -> str:
    """Return the last *n* lines of *path* as a single string."""
    chunk_size = 64 * 1024
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        if size == 0:
            return ""

        blocks: list[bytes] = []
        pos = size
        line_count = 0
        while pos > 0 and line_count <= n:
            read_size = min(chunk_size, pos)
            pos -= read_size
            fh.seek(pos, os.SEEK_SET)
            blocks.insert(0, fh.read(read_size))
            line_count = sum(block.count(b"\n") for block in blocks)

        data = b"".join(blocks)
        text = data.decode("utf-8", errors="replace")
        all_lines = text.splitlines()
        last_lines = all_lines[-n:] if len(all_lines) >= n else all_lines
        return "\n".join(last_lines)


def check_health() -> HealthResult:
    """Check whether the daemon appears healthy.

    Healthy means:
    * at least one evolver loop process is running, **and**
    * the log file has been modified within ``MAX_SILENCE_MS``.
    """
    running = _list_evolver_processes()
    if not running:
        return HealthResult(healthy=False, reason="not_running")

    log_path = get_evolver_log_path()
    if log_path.exists():
        try:
            mtime = log_path.stat().st_mtime
            silence_ms = (time.time() - mtime) * 1000
        except OSError:
            silence_ms = 0.0
        if silence_ms > MAX_SILENCE_MS:
            return HealthResult(
                healthy=False,
                reason="stagnation",
                pids=[p.pid for p in running],
                silence_minutes=int(silence_ms / 60000),
            )

    return HealthResult(healthy=True, pids=[p.pid for p in running])


# ---------------------------------------------------------------------------
# Watch supervisor
# ---------------------------------------------------------------------------


def watch(*, once: bool = False) -> None:
    """Continuous supervisor that checks health and restarts if needed.

    Designed to be run as a lightweight companion process or cron job so
    the daemon self-heals without an external supervisor like systemd/pm2.

    Clock-jump detection
    --------------------
    On macOS, wall-clock time jumps forward after sleep/resume while the
    monotonic clock does not. If the gap exceeds 60 s we skip the stagnation
    check for one tick to give the daemon a grace period.
    """
    interval_s = env_int("EVOLVER_WATCH_INTERVAL_S", 120)
    interval_ms = interval_s * 1000

    prev_wall = time.time()
    prev_mono = time.monotonic()
    skipped_last_tick = False

    def _tick() -> None:
        nonlocal prev_wall, prev_mono, skipped_last_tick
        now_wall = time.time()
        now_mono = time.monotonic()
        wall_delta = now_wall - prev_wall
        mono_delta = now_mono - prev_mono
        clock_jumped = (wall_delta - mono_delta) > 60 and not skipped_last_tick

        health = check_health()
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        if health.healthy:
            logger.info("[Watch] %s healthy pids=%s", ts, ",".join(map(str, health.pids)))
            skipped_last_tick = False
        elif clock_jumped and health.reason == "stagnation":
            logger.info(
                "[Watch] wall-clock jump detected (+%.0fs), skipping stagnation check",
                wall_delta - mono_delta,
            )
            skipped_last_tick = True
        else:
            logger.warning("[Watch] %s unhealthy reason=%s — restarting...", ts, health.reason)
            res = restart()
            logger.info("[Watch] restart result: %s", json.dumps(res.__dict__, default=str))
            skipped_last_tick = False

        prev_wall = now_wall
        prev_mono = now_mono

    _tick()
    if once:
        return

    logger.info("[Watch] Supervisor running every %ds. Ctrl-C to stop.", interval_s)
    try:
        while True:
            _sleep_ms(interval_ms)
            _tick()
    except KeyboardInterrupt:
        logger.info("[Watch] Stopped by user.")


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def env_int(key: str, fallback: int) -> int:
    """Best-effort integer read from the environment."""
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return fallback
    try:
        return int(raw)
    except ValueError:
        return fallback


def _unlink_pid_file() -> None:
    """Remove the PID file; ignore races."""
    pid_file = _pid_file_path()
    try:
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass
