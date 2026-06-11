"""Tests for evolver.evolve.runner daemon loop behavior."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from evolver.evolve import runner


@pytest.fixture
def isolated_evolver_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point all evolver state into tmp_path."""
    monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
    monkeypatch.setenv("GEP_ASSETS_DIR", str(tmp_path / "gep"))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("EVOLVER_USER_LOCK", str(tmp_path / "user.lock"))
    yield tmp_path


@pytest.mark.asyncio
async def test_run_loop_runs_at_least_one_cycle(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Start loop then immediately request shutdown after a short delay
    async def stopper():
        await asyncio.sleep(0.3)
        runner.request_shutdown()

    asyncio.create_task(stopper())
    await runner.run_loop(interval_ms=100)
    captured = capsys.readouterr()
    assert "[loop] Starting daemon loop" in captured.out
    assert "[loop] Graceful shutdown complete." in captured.out
    assert "GENOME EVOLUTION PROTOCOL" in captured.out


@pytest.mark.asyncio
async def test_run_loop_respects_shutdown_between_cycles(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Let it run one cycle, then stop
    call_count = 0

    original_cycle = runner._run_single_cycle

    async def counting_cycle(*, is_loop: bool = False):
        nonlocal call_count
        call_count += 1
        if call_count >= 1:
            runner.request_shutdown()
        return await original_cycle(is_loop=is_loop)

    runner._run_single_cycle = counting_cycle  # type: ignore[assignment]
    try:
        await runner.run_loop(interval_ms=500)
    finally:
        runner._run_single_cycle = original_cycle  # type: ignore[assignment]

    assert call_count >= 1


@pytest.mark.asyncio
async def test_request_shutdown_sets_flag(isolated_evolver_env: Path) -> None:
    runner._shutdown_requested = False
    runner._shutdown_event = asyncio.Event()
    assert not runner._shutdown_requested
    runner.request_shutdown()
    assert runner._shutdown_requested is True
    assert runner._shutdown_event.is_set() is True
