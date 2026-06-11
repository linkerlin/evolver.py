"""Tests for evolver.ops.lifecycle.

Covers: start, stop, restart, status, tail_log, check_health, watch.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import psutil
import pytest

from evolver.ops import lifecycle

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, temp_workspace: Path) -> None:
    """Ensure lifecycle operations target the temp workspace."""
    # Prevent any real process discovery from matching the test runner
    monkeypatch.setenv("EVOLVER_LOOP_COMMAND", f"{sys.executable} -m evolver --loop")


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_process(pid: int, cmdline: list[str]) -> MagicMock:
    m = MagicMock(spec=psutil.Process)
    m.pid = pid
    m.cmdline.return_value = cmdline
    return m


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_no_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lifecycle, "_list_evolver_processes", lambda: [])
    result = lifecycle.status()
    assert result.running is False
    assert result.processes == []


def test_status_with_running(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = [lifecycle.ProcessInfo(pid=12345, cmdline="python -m evolver --loop")]
    monkeypatch.setattr(lifecycle, "_list_evolver_processes", lambda: fake)
    result = lifecycle.status()
    assert result.running is True
    assert len(result.processes) == 1
    assert result.processes[0].pid == 12345


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


def test_start_when_already_running(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = [lifecycle.ProcessInfo(pid=12345, cmdline="python -m evolver --loop")]
    monkeypatch.setattr(lifecycle, "_list_evolver_processes", lambda: fake)
    result = lifecycle.start()
    assert result.status == "already_running"
    assert result.pid == 12345


def test_start_spawns_process(
    monkeypatch: pytest.MonkeyPatch,
    temp_workspace: Path,
) -> None:
    monkeypatch.setattr(lifecycle, "_list_evolver_processes", lambda: [])

    mock_proc = MagicMock()
    mock_proc.pid = 99999

    popen_calls: list[dict[str, Any]] = []

    def fake_popen(**kwargs: Any) -> MagicMock:
        popen_calls.append(kwargs)
        return mock_proc

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = lifecycle.start()
    assert result.status == "started"
    assert result.pid == 99999

    # Verify PID file was written
    pid_file = temp_workspace / "memory" / "evolver_loop.pid"
    assert pid_file.exists()
    assert pid_file.read_text() == "99999"

    # Verify Popen got the right command
    assert len(popen_calls) == 1
    call = popen_calls[0]
    assert call["args"] == [sys.executable, "-m", "evolver", "--loop"]
    assert call["stdin"] is subprocess.DEVNULL
    assert call["cwd"] == str(temp_workspace)


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


def test_stop_no_processes(monkeypatch: pytest.MonkeyPatch, temp_workspace: Path) -> None:
    monkeypatch.setattr(lifecycle, "_list_evolver_processes", lambda: [])
    result = lifecycle.stop()
    assert result.status == "not_running"


def test_stop_sends_sigterm_then_sigkill(
    monkeypatch: pytest.MonkeyPatch,
    temp_workspace: Path,
) -> None:
    target_pid = 55555
    fake = [lifecycle.ProcessInfo(pid=target_pid, cmdline="python -m evolver --loop")]
    monkeypatch.setattr(lifecycle, "_list_evolver_processes", lambda: fake)
    monkeypatch.setattr(lifecycle, "_is_pid_running", lambda pid: pid == target_pid)
    # Force Unix path for consistent signal testing
    monkeypatch.setattr(lifecycle, "platform", SimpleNamespace(system=lambda: "Linux"))

    kill_log: list[tuple[int, int]] = []
    term_count = 0

    def fake_kill(pid: int, sig: int) -> None:
        nonlocal term_count
        kill_log.append((pid, sig))
        if sig == signal.SIGTERM:
            term_count += 1
            # Keep "running" for a few checks, then die on SIGKILL
        if sig == lifecycle._SIGKILL:
            monkeypatch.setattr(lifecycle, "_is_pid_running", lambda p: p != pid)

    def fake_is_pid_running(pid: int) -> bool:
        return pid == target_pid and term_count < 3

    monkeypatch.setattr(os, "kill", fake_kill)
    monkeypatch.setattr(lifecycle, "_is_pid_running", fake_is_pid_running)

    result = lifecycle.stop()
    assert result.status == "stopped"
    assert target_pid in result.killed

    # Should have attempted SIGTERM first
    assert any(pid == target_pid and sig == signal.SIGTERM for pid, sig in kill_log)
    # Should have attempted SIGKILL after grace period
    # On Windows _SIGKILL falls back to SIGTERM, so assert the actual constant used.
    assert any(pid == target_pid and sig == lifecycle._SIGKILL for pid, sig in kill_log)


# ---------------------------------------------------------------------------
# tail_log
# ---------------------------------------------------------------------------


def test_tail_log_no_file() -> None:
    result = lifecycle.tail_log()
    assert result.error is not None
    assert result.content is None


def test_tail_log_returns_last_n_lines(temp_workspace: Path) -> None:
    log_path = temp_workspace / "logs" / "evolution.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"line {i:03d}\n" for i in range(100)]
    log_path.write_text("".join(lines), encoding="utf-8")

    result = lifecycle.tail_log(lines=10)
    assert result.error is None
    assert result.content is not None
    assert result.content.splitlines() == [f"line {i:03d}" for i in range(90, 100)]


def test_tail_log_ignores_trailing_newline(temp_workspace: Path) -> None:
    log_path = temp_workspace / "logs" / "evolution.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("a\nb\nc\n", encoding="utf-8")

    result = lifecycle.tail_log(lines=5)
    # splitlines/join normalises trailing newlines away
    assert result.content == "a\nb\nc"


# ---------------------------------------------------------------------------
# check_health
# ---------------------------------------------------------------------------


def test_check_health_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lifecycle, "_list_evolver_processes", lambda: [])
    result = lifecycle.check_health()
    assert result.healthy is False
    assert result.reason == "not_running"


def test_check_health_stagnation(
    monkeypatch: pytest.MonkeyPatch,
    temp_workspace: Path,
) -> None:
    fake = [lifecycle.ProcessInfo(pid=11111, cmdline="python -m evolver --loop")]
    monkeypatch.setattr(lifecycle, "_list_evolver_processes", lambda: fake)

    # Create a log file older than MAX_SILENCE_MS
    log_path = temp_workspace / "logs" / "evolution.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("old log", encoding="utf-8")
    old_time = time.time() - (lifecycle.MAX_SILENCE_MS / 1000.0 + 60)
    os.utime(log_path, (old_time, old_time))

    result = lifecycle.check_health()
    assert result.healthy is False
    assert result.reason == "stagnation"
    assert result.silence_minutes is not None
    assert result.silence_minutes > 0


def test_check_health_healthy(
    monkeypatch: pytest.MonkeyPatch,
    temp_workspace: Path,
) -> None:
    fake = [lifecycle.ProcessInfo(pid=11111, cmdline="python -m evolver --loop")]
    monkeypatch.setattr(lifecycle, "_list_evolver_processes", lambda: fake)

    log_path = temp_workspace / "logs" / "evolution.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("recent log", encoding="utf-8")

    result = lifecycle.check_health()
    assert result.healthy is True
    assert result.pids == [11111]


# ---------------------------------------------------------------------------
# restart
# ---------------------------------------------------------------------------


def test_restart_calls_stop_then_start(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_stop() -> lifecycle.StopResult:
        calls.append("stop")
        return lifecycle.StopResult(status="stopped")

    def fake_start(*, delay_ms: int = 0) -> lifecycle.StartResult:
        calls.append("start")
        return lifecycle.StartResult(status="started", pid=42)

    monkeypatch.setattr(lifecycle, "stop", fake_stop)
    monkeypatch.setattr(lifecycle, "start", fake_start)

    result = lifecycle.restart()
    assert calls == ["stop", "start"]
    assert result.status == "started"
    assert result.pid == 42


# ---------------------------------------------------------------------------
# watch (supervisor)
# ---------------------------------------------------------------------------


def test_watch_once_restarts_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    health_calls = 0

    def fake_check_health() -> lifecycle.HealthResult:
        nonlocal health_calls
        health_calls += 1
        return lifecycle.HealthResult(healthy=False, reason="not_running")

    restart_calls = 0

    def fake_restart() -> lifecycle.StartResult:
        nonlocal restart_calls
        restart_calls += 1
        return lifecycle.StartResult(status="started", pid=77)

    monkeypatch.setattr(lifecycle, "check_health", fake_check_health)
    monkeypatch.setattr(lifecycle, "restart", fake_restart)

    lifecycle.watch(once=True)
    assert health_calls == 1
    assert restart_calls == 1


def test_watch_once_does_nothing_when_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    health_calls = 0

    def fake_check_health() -> lifecycle.HealthResult:
        nonlocal health_calls
        health_calls += 1
        return lifecycle.HealthResult(healthy=True, pids=[123])

    restart_calls = 0

    def fake_restart() -> lifecycle.StartResult:
        nonlocal restart_calls
        restart_calls += 1
        return lifecycle.StartResult(status="started", pid=77)

    monkeypatch.setattr(lifecycle, "check_health", fake_check_health)
    monkeypatch.setattr(lifecycle, "restart", fake_restart)

    lifecycle.watch(once=True)
    assert health_calls == 1
    assert restart_calls == 0


# ---------------------------------------------------------------------------
# _tail_file edge cases
# ---------------------------------------------------------------------------


def test_tail_file_empty(temp_workspace: Path) -> None:
    p = temp_workspace / "empty.log"
    p.write_text("", encoding="utf-8")
    assert lifecycle._tail_file(p, 10) == ""


def test_tail_file_more_lines_than_exist(temp_workspace: Path) -> None:
    p = temp_workspace / "short.log"
    p.write_text("a\nb\n", encoding="utf-8")
    assert lifecycle._tail_file(p, 100) == "a\nb"


def test_tail_file_binary_fallback(temp_workspace: Path) -> None:
    p = temp_workspace / "binary.log"
    p.write_bytes(b"\xff\xfe" + b"\na\nb\n" * 50)
    result = lifecycle._tail_file(p, 5)
    assert isinstance(result, str)
    # Should not raise despite invalid UTF-8 at the start
    assert "a" in result


# ---------------------------------------------------------------------------
# CLI integration smoke tests
# ---------------------------------------------------------------------------


def test_cli_start_stop_cycle(monkeypatch: pytest.MonkeyPatch, temp_workspace: Path) -> None:
    """End-to-end CLI smoke: start -> status -> stop -> status."""
    from evolver.cli import main

    monkeypatch.setattr(lifecycle, "_list_evolver_processes", lambda: [])

    mock_proc = MagicMock()
    mock_proc.pid = 77777
    monkeypatch.setattr(subprocess, "Popen", lambda **kwargs: mock_proc)

    # start
    assert main(["start"]) == 0
    assert (temp_workspace / "memory" / "evolver_loop.pid").exists()

    # status (running)
    fake = [lifecycle.ProcessInfo(pid=77777, cmdline="python -m evolver --loop")]
    monkeypatch.setattr(lifecycle, "_list_evolver_processes", lambda: fake)
    assert main(["status"]) == 0

    # stop
    kill_log: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: kill_log.append((pid, sig)))
    monkeypatch.setattr(lifecycle, "_is_pid_running", lambda pid: False)
    assert main(["stop"]) == 0

    # status (not running)
    monkeypatch.setattr(lifecycle, "_list_evolver_processes", lambda: [])
    assert main(["status"]) == 0
