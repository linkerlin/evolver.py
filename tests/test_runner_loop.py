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
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("EVOLVER_NO_PARENT_GIT", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("EVOLVER_USER_LOCK", str(tmp_path / "user.lock"))
    # Keep progress ticker from sleeping 60s in short tests.
    monkeypatch.setenv("EVOLVER_PROGRESS_UPDATE_MS", "1000")
    yield tmp_path


@pytest.mark.asyncio
async def test_a_sessionless_tick_stops_and_writes_no_gene(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Charter §5.5 completion: a tick with no running session returns
    ``stop_and_report`` and writes no gene — the loop continues sessions,
    it does not open them, and it does not idle-spin either.

    (Supersedes the old "loop runs a full GEP cycle" pin: since the loop
    gate, a sessionless daemon never reaches the pipeline, so the GEP
    protocol header can no longer be its assertion.)
    """
    result = await runner._run_single_cycle(is_loop=True)
    assert result["next_action"] == "stop_and_report"
    assert result["loop_without_session"] is True
    assert result["loop_stop_reason"] == "no_running_session"
    assert "selected_gene" not in result
    assert "dispatch_prompt" not in result

    # The daemon honors the verdict: it breaks instead of re-ticking.
    await runner.run_loop(interval_ms=100)
    out = capsys.readouterr().out
    assert "no_running_session — stopping." in out
    assert "GENOME EVOLUTION PROTOCOL" not in out, "no cycle ran, so no gene work"
    assert "[loop] Graceful shutdown complete." in out


@pytest.mark.asyncio
async def test_a_due_reminder_still_stops_but_rides_along(
    isolated_evolver_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Even when the cursor's reminder is due, the tick's verdict is the
    same: stop. The reminder is an invitation to a human, never a command —
    the only difference is that it rides in the stop report."""
    from evolver.gep import cursor

    cursor.save_cursor(recorded_at="2020-01-01T00:00:00Z")  # far past due

    result = await runner._run_single_cycle(is_loop=True)
    assert result["next_action"] == "stop_and_report"
    assert result["cursor_reminder"]["due"] is True
    assert "name a session yourself" in result["cursor_reminder"]["action"]

    await runner.run_loop(interval_ms=100)
    out = capsys.readouterr().out
    assert "Evolution reminder" in out
    assert "no_running_session — stopping." in out


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
