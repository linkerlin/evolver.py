"""Validator daemon — poll Hub for validation tasks and execute them in sandboxes.

Equivalent to Node's ``evolver/src/gep/validator/index.js``.

The daemon runs a background loop that:
1. Polls the Hub ``/a2a/validator/tasks`` endpoint every 30 s.
2. Claims tasks up to ``MAX_CONCURRENT_VALIDATIONS`` (default 3).
3. Dispatches each task to :mod:`sandbox_executor`.
4. Submits results via :mod:`reporter`.
5. Handles graceful shutdown on SIGTERM (waits up to 60 s for inflight tasks).

Lifecycle
---------
* ``start()`` — begin polling loop in a background thread.
* ``stop()`` — signal shutdown, wait for inflight tasks.
* ``is_running()`` — check daemon state.

Environment
-----------
* ``EVOLVER_VALIDATOR_ENABLED`` — default ``1`` (ON).
* ``MAX_CONCURRENT_VALIDATIONS`` — default ``3``.

Design notes
------------
* Uses ``threading.Thread`` for the polling loop.
* Task queue is an in-memory ``deque``.
* Inflight tasks are tracked in a ``set`` of futures / threads.
* Exponential backoff on Hub errors (max 5 min).
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from evolver.gep.validator.reporter import submit_report
from evolver.gep.validator.sandbox_executor import SandboxResult, execute_in_sandbox

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 30.0
DEFAULT_MAX_CONCURRENT = 3
DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT = 60.0

# Backoff config
BACKOFF_BASE = 1.0
BACKOFF_MAX = 300.0  # 5 min


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ValidationTask:
    task_id: str
    script_content: str
    script_filename: str = "validate.py"
    timeout_seconds: float = 180.0
    claimed_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Hub client (best-effort, may be mocked)
# ---------------------------------------------------------------------------


def _poll_tasks() -> list[ValidationTask]:
    """Poll Hub for open validator tasks."""
    try:
        from evolver.atp.hub_client import list_validator_tasks
        import asyncio
        try:
            raw_tasks = asyncio.run(list_validator_tasks())
        except RuntimeError:
            loop = asyncio.get_event_loop()
            raw_tasks = loop.run_until_complete(list_validator_tasks())
        tasks: list[ValidationTask] = []
        for t in raw_tasks:
            tasks.append(
                ValidationTask(
                    task_id=t.get("task_id", ""),
                    script_content=t.get("script", ""),
                    script_filename=t.get("filename", "validate.py"),
                    timeout_seconds=float(t.get("timeout", 180.0)),
                )
            )
        return tasks
    except Exception as exc:
        logger.debug("[ValidatorDaemon] Poll failed: %s", exc)
        return []


def _claim_task(task_id: str) -> bool:
    try:
        from evolver.atp.hub_client import claim_validator_task
        import asyncio
        try:
            result = asyncio.run(claim_validator_task(task_id))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            result = loop.run_until_complete(claim_validator_task(task_id))
        return bool(result)
    except Exception as exc:
        logger.debug("[ValidatorDaemon] Claim failed for %s: %s", task_id, exc)
        return False


# ---------------------------------------------------------------------------
# Daemon
# ---------------------------------------------------------------------------


class ValidatorDaemon:
    def __init__(
        self,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        shutdown_timeout: float = DEFAULT_GRACEFUL_SHUTDOWN_TIMEOUT,
    ) -> None:
        self.poll_interval = poll_interval
        self.max_concurrent = max_concurrent
        self.shutdown_timeout = shutdown_timeout

        self._running = False
        self._shutdown_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._inflight: set[str] = set()
        self._lock = threading.Lock()
        self._backoff = BACKOFF_BASE

    def start(self) -> None:
        """Start the validator daemon in a background thread."""
        if self._running:
            logger.warning("[ValidatorDaemon] Already running")
            return
        self._running = True
        self._shutdown_event.clear()
        self._thread = threading.Thread(target=self._loop, name="ValidatorDaemon", daemon=True)
        self._thread.start()
        logger.info("[ValidatorDaemon] Started (poll=%.0fs, max_concurrent=%d)", self.poll_interval, self.max_concurrent)

    def stop(self) -> None:
        """Signal shutdown and wait for inflight tasks (up to *shutdown_timeout*)."""
        if not self._running:
            return
        logger.info("[ValidatorDaemon] Stopping...")
        self._running = False
        self._shutdown_event.set()

        deadline = time.time() + self.shutdown_timeout
        while time.time() < deadline:
            with self._lock:
                if not self._inflight:
                    break
            time.sleep(0.5)

        with self._lock:
            if self._inflight:
                logger.warning("[ValidatorDaemon] %d task(s) still inflight after timeout", len(self._inflight))

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        logger.info("[ValidatorDaemon] Stopped")

    def is_running(self) -> bool:
        return self._running

    def _loop(self) -> None:
        while self._running and not self._shutdown_event.is_set():
            try:
                self._tick()
                self._backoff = BACKOFF_BASE
            except Exception as exc:
                logger.warning("[ValidatorDaemon] Tick error: %s", exc)
                time.sleep(self._backoff)
                self._backoff = min(BACKOFF_MAX, self._backoff * 2)
                continue

            # Sleep with early wake on shutdown
            if self._shutdown_event.wait(self.poll_interval):
                break

    def _tick(self) -> None:
        # Check concurrency limit
        with self._lock:
            if len(self._inflight) >= self.max_concurrent:
                return

        tasks = _poll_tasks()
        for task in tasks:
            with self._lock:
                if len(self._inflight) >= self.max_concurrent:
                    break

            if not _claim_task(task.task_id):
                continue

            with self._lock:
                self._inflight.add(task.task_id)

            # Run sandbox in a thread
            t = threading.Thread(
                target=self._run_task,
                args=(task,),
                name=f"ValidatorTask-{task.task_id}",
                daemon=True,
            )
            t.start()

    def _run_task(self, task: ValidationTask) -> None:
        try:
            logger.info("[ValidatorDaemon] Running task %s", task.task_id)
            result = execute_in_sandbox(
                script_content=task.script_content,
                script_filename=task.script_filename,
                timeout_seconds=task.timeout_seconds,
            )
            report = {
                "task_id": task.task_id,
                "status": _map_status(result),
                "score": 1.0 if result.exit_code == 0 else 0.0,
                "execution_log": result.stdout + "\n" + result.stderr,
                "execution_time_ms": result.elapsed_ms,
                "sandbox_version": "python-3.13",
            }
            submit_report(report)
        except Exception as exc:
            logger.warning("[ValidatorDaemon] Task %s failed: %s", task.task_id, exc)
            submit_report({
                "task_id": task.task_id,
                "status": "error",
                "score": 0.0,
                "execution_log": str(exc),
                "execution_time_ms": 0.0,
                "sandbox_version": "python-3.13",
            })
        finally:
            with self._lock:
                self._inflight.discard(task.task_id)


def _map_status(result: SandboxResult) -> str:
    if result.timed_out:
        return "timeout"
    if result.exit_code == 0:
        return "passed"
    return "failed"


# ---------------------------------------------------------------------------
# Singleton convenience
# ---------------------------------------------------------------------------

_default_daemon: ValidatorDaemon | None = None


def start_validator() -> ValidatorDaemon:
    """Start the global validator daemon."""
    global _default_daemon
    if _default_daemon is None:
        _default_daemon = ValidatorDaemon()
    _default_daemon.start()
    return _default_daemon


def stop_validator() -> None:
    """Stop the global validator daemon."""
    global _default_daemon
    if _default_daemon is not None:
        _default_daemon.stop()
