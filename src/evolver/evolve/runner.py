"""Main evolution runner.

Equivalent to evolver/src/evolve.js (obfuscated in Node).
"""

from __future__ import annotations

import asyncio
import datetime
import secrets
import time
from typing import Any

from evolver.config import IDLE_FETCH_INTERVAL_MS
from evolver.evolve import guards
from evolver.evolve.pipeline import (
    collect_phase,
    dispatch_phase,
    enrich_phase,
    hub_phase,
    select_phase,
    signals_phase,
)
from evolver.evolve.post_cycle import run_post_cycle_hooks
from evolver.gep.instance_lock import instance_lock_ctx
from evolver.gep.paths import get_cycle_progress_path
from evolver.ops.cleanup import run_cleanup

# Daemon loop coordination
_shutdown_requested: bool = False
_shutdown_event: asyncio.Event | None = None


def _current_event() -> asyncio.Event | None:
    global _shutdown_event
    return _shutdown_event


def request_shutdown() -> None:
    """Request graceful shutdown of the daemon loop."""
    global _shutdown_requested
    _shutdown_requested = True
    ev = _current_event()
    if ev is not None:
        ev.set()


def _build_initial_context() -> dict[str, Any]:
    return {
        "run_id": f"run_{int(time.time() * 1000)}_{secrets.token_hex(4)}",
        "cycle_num": 1,
        "cycle_id": secrets.token_hex(8),
        "IS_RANDOM_DRIFT": False,
        "IS_REVIEW_MODE": False,
        "IS_DRY_RUN": False,
        "bridge_enabled": guards.determine_bridge_enabled(),
        "AGENT_NAME": __import__("os").environ.get("AGENT_NAME", "main"),
        "scan_time_iso": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
    }


async def _run_single_cycle(*, is_loop: bool = False) -> dict[str, Any]:
    """Execute one full evolution cycle and return the final context."""
    ctx = _build_initial_context()
    preflight = await guards.run_preflight_checks(is_loop=is_loop)
    if preflight.abort:
        print(f"Preflight abort: {preflight.reason}")
        return ctx

    ctx = await collect_phase(ctx)
    ctx = await signals_phase(ctx)
    ctx = await hub_phase(ctx)
    ctx = await enrich_phase(ctx)
    ctx = await select_phase(ctx)
    ctx = await dispatch_phase(ctx)
    ctx = await run_post_cycle_hooks(ctx)
    return ctx


async def run() -> None:
    """Single evolution cycle (public API)."""
    await _run_single_cycle(is_loop=False)


async def run_loop(
    *,
    interval_ms: int | None = None,
    review_mode: bool = False,
    dry_run: bool = False,
) -> None:
    """Daemon loop: run evolution cycles with configurable interval.

    Stops gracefully when :func:`request_shutdown` is called.
    Acquires a single-instance lock to prevent multiple daemons.
    """
    global _shutdown_requested, _shutdown_event
    interval = (interval_ms or IDLE_FETCH_INTERVAL_MS) / 1000.0
    interval = max(interval, 1.0)

    # Single-instance lock
    acquired = instance_lock_ctx(blocking=False, timeout=0)
    with acquired as lock_ok:
        if not lock_ok:
            print("[loop] Another evolver daemon is already running. Exiting.")
            return

        _shutdown_requested = False
        _shutdown_event = asyncio.Event()
        shutdown = _shutdown_event

        consecutive_errors = 0
        max_backoff_interval = min(300.0, interval * 8)

        print(f"[loop] Starting daemon loop (interval={interval:.1f}s, review={review_mode})")

        cycle_count = 0
        last_cleanup_cycle = 0

        while not shutdown.is_set() and not _shutdown_requested:
            cycle_count += 1
            _write_cycle_progress(cycle_count, consecutive_errors)

            try:
                if review_mode:
                    print("[loop] Review mode active — pausing before cycle.")
                    print("       Press Enter to continue, or send SIGINT to stop.")
                    # Non-blocking attempt to read a line; if shutdown fires first, break.
                    input_task = asyncio.create_task(asyncio.to_thread(input))
                    shutdown_task = asyncio.create_task(shutdown.wait())
                    _done, pending = await asyncio.wait(
                        [input_task, shutdown_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending:
                        task.cancel()
                    if shutdown.is_set() or _shutdown_requested:
                        break

                await _run_single_cycle(is_loop=True)
                consecutive_errors = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                consecutive_errors += 1
                backoff = min(interval * (2 ** (consecutive_errors - 1)), max_backoff_interval)
                print(f"[loop] Cycle failed ({consecutive_errors}): {exc}")
                print(f"[loop] Backing off for {backoff:.1f}s")
                try:
                    await asyncio.wait_for(shutdown.wait(), timeout=backoff)
                except TimeoutError:
                    pass
                continue

            # Periodic cleanup every 10 cycles
            if cycle_count - last_cleanup_cycle >= 10:
                last_cleanup_cycle = cycle_count
                try:
                    cleanup_result = run_cleanup()
                    if cleanup_result.get("total_removed", 0) > 0:
                        print(
                            f"[loop] Cleanup removed {cleanup_result['total_removed']} stale items."
                        )
                except Exception as exc:
                    print(f"[loop] Cleanup error: {exc}")

            # Sleep until next cycle or shutdown
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=interval)
            except TimeoutError:
                pass

        print("[loop] Graceful shutdown complete.")


def _write_cycle_progress(cycle_count: int, consecutive_errors: int) -> None:
    """Atomically write cycle progress to disk."""
    import json

    path = get_cycle_progress_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "cycle_count": cycle_count,
        "consecutive_errors": consecutive_errors,
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
