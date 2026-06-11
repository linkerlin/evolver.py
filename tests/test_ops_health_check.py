"""Tests for evolver.ops.health_check."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import psutil
import pytest

from evolver.ops import health_check

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_check(report: health_check.HealthReport, name: str) -> health_check.CheckResult | None:
    for c in report.checks:
        if c.name == name:
            return c
    return None


# ---------------------------------------------------------------------------
# Secret checks
# ---------------------------------------------------------------------------


def test_secret_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    report = health_check.run_health_check()
    secret_check = _find_check(report, "env:OPENAI_API_KEY")
    assert secret_check is not None
    assert secret_check.ok is True
    assert secret_check.status == "present"


def test_secret_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    report = health_check.run_health_check()
    secret_check = _find_check(report, "env:OPENAI_API_KEY")
    assert secret_check is not None
    assert secret_check.ok is False
    assert secret_check.status == "missing"
    assert secret_check.severity == "info"


# ---------------------------------------------------------------------------
# Disk checks
# ---------------------------------------------------------------------------


def test_disk_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_usage = MagicMock()
    mock_usage.total = 100 * 1024 * 1024
    mock_usage.used = 50 * 1024 * 1024
    monkeypatch.setattr("shutil.disk_usage", lambda _p: mock_usage)

    report = health_check.run_health_check()
    disk = _find_check(report, "disk_space")
    assert disk is not None
    assert disk.ok is True
    assert disk.status == "50% used"


def test_disk_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_usage = MagicMock()
    mock_usage.total = 100 * 1024 * 1024
    mock_usage.used = 85 * 1024 * 1024
    monkeypatch.setattr("shutil.disk_usage", lambda _p: mock_usage)

    report = health_check.run_health_check()
    assert report.status == "warning"
    disk = _find_check(report, "disk_space")
    assert disk is not None
    assert disk.ok is False
    assert disk.severity == "warning"


def test_disk_critical(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_usage = MagicMock()
    mock_usage.total = 100 * 1024 * 1024
    mock_usage.used = 95 * 1024 * 1024
    monkeypatch.setattr("shutil.disk_usage", lambda _p: mock_usage)

    report = health_check.run_health_check()
    assert report.status == "error"
    disk = _find_check(report, "disk_space")
    assert disk is not None
    assert disk.ok is False
    assert disk.severity == "critical"


def test_disk_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_p: Any) -> Any:
        raise OSError("Permission denied")

    monkeypatch.setattr("shutil.disk_usage", boom)
    report = health_check.run_health_check()
    disk = _find_check(report, "disk_space")
    assert disk is not None
    assert disk.ok is False
    assert "Permission denied" in disk.status


# ---------------------------------------------------------------------------
# Memory checks
# ---------------------------------------------------------------------------


def test_memory_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_mem = MagicMock()
    mock_mem.percent = 60.0
    monkeypatch.setattr(psutil, "virtual_memory", lambda: mock_mem)

    report = health_check.run_health_check()
    mem = _find_check(report, "memory")
    assert mem is not None
    assert mem.ok is True
    assert mem.status == "60% used"


def test_memory_critical(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_mem = MagicMock()
    mock_mem.percent = 98.0
    monkeypatch.setattr(psutil, "virtual_memory", lambda: mock_mem)

    report = health_check.run_health_check()
    assert report.status == "error"
    mem = _find_check(report, "memory")
    assert mem is not None
    assert mem.ok is False
    assert mem.severity == "critical"


# ---------------------------------------------------------------------------
# Process count
# ---------------------------------------------------------------------------


def test_process_count_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(psutil, "pids", lambda: list(range(100)))
    # bust cache
    health_check._proc_cache = None
    report = health_check.run_health_check()
    proc = _find_check(report, "process_count")
    assert proc is not None
    assert proc.ok is True


def test_process_count_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(psutil, "pids", lambda: list(range(2500)))
    health_check._proc_cache = None
    report = health_check.run_health_check()
    proc = _find_check(report, "process_count")
    assert proc is not None
    assert proc.ok is False
    assert proc.severity == "warning"


def test_process_count_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    health_check._proc_cache = (__import__("time").time(), 42)
    monkeypatch.setattr(psutil, "pids", lambda: list(range(9999)))
    report = health_check.run_health_check()
    proc = _find_check(report, "process_count")
    assert proc is not None
    assert proc.status == "42 procs"  # cached value, not 9999


# ---------------------------------------------------------------------------
# Overall status
# ---------------------------------------------------------------------------


def test_overall_ok() -> None:
    report = health_check.run_health_check()
    assert report.status in ("ok", "warning", "error")
    assert report.timestamp
    assert report.checks


def test_custom_optional_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_SECRET", "value")
    report = health_check.run_health_check(optional_secrets=["MY_SECRET", "MISSING"])
    present = _find_check(report, "env:MY_SECRET")
    missing = _find_check(report, "env:MISSING")
    assert present is not None and present.ok is True
    assert missing is not None and missing.ok is False
