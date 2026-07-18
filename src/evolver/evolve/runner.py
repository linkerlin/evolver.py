"""Main evolution runner.

Equivalent to evolver/src/evolve.js (obfuscated in Node).
"""

from __future__ import annotations

import asyncio
import datetime
import os
import secrets
import time
from typing import Any

from evolver.config import IDLE_FETCH_INTERVAL_MS, MAX_CYCLES_PER_PROCESS
from evolver.cycle_control import (
    CycleTimeoutError,
    cycle_timeout_enabled,
    cycle_timeout_ms,
    handle_cycle_timeout,
    progress_update_ms,
    spawn_replacement_process,
    wait_for_timed_out_task,
    write_cycle_progress_atomic,
)
from evolver.evolve import guards
from evolver.evolve.pipeline import (
    autopoiesis_phase,
    collect_phase,
    dispatch_phase,
    enrich_phase,
    hub_phase,
    select_phase,
    signals_phase,
)
from evolver.evolve.post_cycle import run_post_cycle_hooks
from evolver.gep.bridge import determine_bridge_enabled
from evolver.gep.instance_lock import instance_lock_ctx
from evolver.gep.paths import get_cycle_progress_path, get_logs_dir
from evolver.ops.cleanup import run_cleanup

# Daemon loop coordination
_shutdown_requested: bool = False
_shutdown_event: asyncio.Event | None = None

#: When bridge mode is active, a dispatched sessions_spawn(...) starts a "pending
#: bridge run". If the run does not complete within this timeout (seconds), the
#: loop treats it as stale and breaks — preventing a "Ralph-loop" where the
#: daemon keeps re-spawning sessions that never finish (#559).
BRIDGE_STALE_TIMEOUT_S: float = float(
    __import__("os").environ.get("EVOLVER_BRIDGE_STALE_TIMEOUT_S", "600")
)


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
        "bridge_enabled": determine_bridge_enabled(),
        "AGENT_NAME": __import__("os").environ.get("AGENT_NAME", "main"),
        "scan_time_iso": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
    }


async def _run_single_cycle(*, is_loop: bool = False) -> dict[str, Any]:
    """Execute one full evolution cycle and return the final context."""
    ctx = _build_initial_context()
    preflight = await guards.run_preflight_checks(is_loop=is_loop)
    if preflight.abort:
        print(f"Preflight abort: {preflight.reason}")
        try:
            from evolver.gep.autopoiesis import run_preflight_abort_self_report

            abort_report = run_preflight_abort_self_report(preflight.reason or "unknown")
            if abort_report:
                ctx["autopoiesis_preflight_abort"] = abort_report
        except Exception:
            pass
        return ctx
    if preflight.repair_loop_degraded:
        print(f"Preflight degraded (repair-only): {preflight.reason}")
        ctx["repair_loop_degraded"] = True
        ctx["autopoiesis_repair_bias"] = True
        ctx["IS_RANDOM_DRIFT"] = False

    ctx = await collect_phase(ctx)
    ctx = await signals_phase(ctx)
    ctx = await hub_phase(ctx)
    ctx = await enrich_phase(ctx)
    ctx = await autopoiesis_phase(ctx)
    ctx = await select_phase(ctx)
    ctx = await dispatch_phase(ctx)
    ctx = await run_post_cycle_hooks(ctx)
    try:
        from evolver.gep.autopoiesis import clear_preflight_abort_report

        clear_preflight_abort_report()
    except Exception:
        pass
    return ctx


async def run() -> None:
    """Single evolution cycle (public API)."""
    await _run_single_cycle(is_loop=False)


async def run_loop(  # noqa: PLR0912, PLR0915
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
        # Track a pending bridge-mode run to detect staleness (#559).
        pending_bridge_ts: float | None = None

        while not shutdown.is_set() and not _shutdown_requested:
            cycle_count += 1

            # Stale bridge-run detection: if the previous cycle dispatched a
            # sessions_spawn(...) in bridge mode and it hasn't completed within
            # BRIDGE_STALE_TIMEOUT_S, break the loop instead of re-spawning
            # forever (the "Ralph-loop" fix #559).
            if pending_bridge_ts is not None:
                stale_age = time.time() - pending_bridge_ts
                if stale_age > BRIDGE_STALE_TIMEOUT_S:
                    print(
                        f"[loop] Bridge-mode pending run is stale "
                        f"({stale_age:.0f}s > {BRIDGE_STALE_TIMEOUT_S:.0f}s). "
                        "Breaking loop to avoid re-spawn storm (#559)."
                    )
                    break

            t0_ms = int(time.time() * 1000)
            progress_path = get_cycle_progress_path()
            progress_fields: dict[str, Any] = {
                "pid": os.getpid(),
                "outer_cycle": cycle_count,
                "inner_cycle": cycle_count,
                "started_at": t0_ms,
                "phase": "evolve.run",
                "cycle_count": cycle_count,
                "consecutive_errors": consecutive_errors,
            }
            write_cycle_progress_atomic(progress_path, progress_fields)

            progress_ticker: asyncio.Task[None] | None = None
            evolve_task: asyncio.Task[dict[str, Any]] | None = None
            ctx: dict[str, Any] = {}
            try:
                if review_mode:
                    print("[loop] Review mode active — pausing before cycle.")
                    print("       Press Enter to continue, or send SIGINT to stop.")
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

                evolve_task = asyncio.create_task(_run_single_cycle(is_loop=True))
                # Progress ticker: refresh updated_at while cycle is in flight.
                progress_ticker = asyncio.create_task(
                    _progress_ticker(progress_path, progress_fields)
                )

                if cycle_timeout_enabled():
                    timeout_s = cycle_timeout_ms() / 1000.0
                    try:
                        ctx = await asyncio.wait_for(asyncio.shield(evolve_task), timeout=timeout_s)
                    except TimeoutError as te:
                        err = CycleTimeoutError(cycle_timeout_ms(), "evolve.run", cycle_count)
                        action = handle_cycle_timeout(
                            error=err,
                            cycle_progress_path=progress_path,
                            progress_fields=progress_fields,
                            args=["--loop"],
                            log_path=get_logs_dir() / "evolver-daemon.log",
                            spawn_replacement_fn=spawn_replacement_process,
                        )
                        if action["action"] == "respawn":
                            # Supervisor restarts on exit 1 (Windows default skip path).
                            raise SystemExit(1) from te
                        # Non-fatal: wait for the timed-out task before next cycle.
                        await wait_for_timed_out_task(evolve_task)
                        consecutive_errors += 1
                        if MAX_CYCLES_PER_PROCESS and cycle_count >= MAX_CYCLES_PER_PROCESS:
                            print(
                                f"[loop] Reached EVOLVER_MAX_CYCLES_PER_PROCESS="
                                f"{MAX_CYCLES_PER_PROCESS} after timeout."
                            )
                            break
                        continue
                else:
                    ctx = await evolve_task

                consecutive_errors = 0

                # Track pending bridge runs: if the cycle produced a spawn
                # directive in bridge mode, stamp the timestamp.
                if ctx.get("bridge_enabled") and ctx.get("bridge_spawn_dispatched"):
                    pending_bridge_ts = time.time()
                else:
                    pending_bridge_ts = None
            except SystemExit:
                raise
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
            finally:
                if progress_ticker is not None:
                    progress_ticker.cancel()
                    with __import__("contextlib").suppress(asyncio.CancelledError, Exception):
                        await progress_ticker

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
            # Solo/CI testability: stop after a bounded number of cycles.
            if MAX_CYCLES_PER_PROCESS and cycle_count >= MAX_CYCLES_PER_PROCESS:
                print(f"[loop] Reached EVOLVER_MAX_CYCLES_PER_PROCESS={MAX_CYCLES_PER_PROCESS}.")
                result = spawn_replacement_process(
                    reason="max_cycles_or_rss",
                    args=["--loop"],
                    log_path=get_logs_dir() / "evolver-daemon.log",
                )
                if result.get("spawned"):
                    print("[loop] Replacement spawned; exiting for handoff (exit 1).")
                    raise SystemExit(1)
                if result.get("reason") == "windows_default_skip":
                    print("[loop] Windows default: exit 1 so external supervisor can respawn.")
                    raise SystemExit(1)
                # spawn_error / test doubles: exit loop gracefully without killing pytest.
                break
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=interval)
            except TimeoutError:
                pass

        print("[loop] Graceful shutdown complete.")


async def _progress_ticker(progress_path: Any, fields: dict[str, Any]) -> None:
    """Refresh cycle_progress.updated_at while a cycle is running."""
    interval = max(progress_update_ms() / 1000.0, 1.0)
    try:
        while True:
            await asyncio.sleep(interval)
            write_cycle_progress_atomic(progress_path, {**fields, "phase": "evolve.run"})
    except asyncio.CancelledError:
        return


def _write_cycle_progress(cycle_count: int, consecutive_errors: int) -> bool:
    """Compat wrapper: atomic progress write used by older call sites."""
    return write_cycle_progress_atomic(
        get_cycle_progress_path(),
        {
            "pid": os.getpid(),
            "outer_cycle": cycle_count,
            "inner_cycle": cycle_count,
            "cycle_count": cycle_count,
            "consecutive_errors": consecutive_errors,
            "phase": "evolve.run",
            "started_at": int(time.time() * 1000),
        },
    )
