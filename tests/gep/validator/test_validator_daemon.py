"""Tests for evolver.gep.validator.ValidatorDaemon."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

from evolver.gep.validator import ValidatorDaemon
from evolver.gep.validator.sandbox_executor import SandboxResult


def _wait_for(condition: callable, timeout: float = 2.0) -> bool:  # type: ignore[no-redef]
    start = time.time()
    while time.time() - start < timeout:
        if condition():
            return True
        time.sleep(0.01)
    return False


class TestLifecycle:
    def test_start_stop(self):
        daemon = ValidatorDaemon(poll_interval=0.1)
        assert not daemon.is_running()
        daemon.start()
        assert daemon.is_running()
        daemon.stop()
        assert not daemon.is_running()

    def test_double_start_is_noop(self):
        daemon = ValidatorDaemon(poll_interval=0.1)
        daemon.start()
        daemon.start()  # should not crash or spawn second thread
        assert daemon.is_running()
        daemon.stop()

    def test_stop_when_not_running_is_noop(self):
        daemon = ValidatorDaemon(poll_interval=0.1)
        daemon.stop()  # should not crash
        assert not daemon.is_running()

    def test_graceful_shutdown_waits_for_inflight(self):
        daemon = ValidatorDaemon(poll_interval=60.0, shutdown_timeout=5.0)
        daemon.start()

        task_finished = threading.Event()

        def slow_task():
            with daemon._lock:
                daemon._inflight.add("t1")
            time.sleep(0.2)
            task_finished.set()
            with daemon._lock:
                daemon._inflight.discard("t1")

        runner = threading.Thread(target=slow_task)
        runner.start()

        assert _wait_for(lambda: "t1" in daemon._inflight)
        daemon.stop()

        assert task_finished.is_set(), "Shutdown did not wait for inflight task"
        runner.join(timeout=1.0)


class TestTickAndExecute:
    def _make_fake_task(self, task_id: str, content: str = "print('ok')") -> MagicMock:
        t = MagicMock()
        t.task_id = task_id
        t.script_content = content
        t.script_filename = "validate.py"
        t.timeout_seconds = 5.0
        return t

    def test_poll_and_execute_task(self):
        daemon = ValidatorDaemon(poll_interval=60.0)
        daemon.start()

        fake_task = self._make_fake_task("t1")
        run_started = threading.Event()
        report_submitted = threading.Event()

        def fake_run_task(task):
            with daemon._lock:
                daemon._inflight.add(task.task_id)
            run_started.set()
            result = SandboxResult(
                exit_code=0, stdout="ok", stderr="", timed_out=False, elapsed_ms=10.0
            )
            report = {
                "task_id": task.task_id,
                "status": "passed",
                "score": 1.0,
                "execution_log": result.stdout,
                "execution_time_ms": result.elapsed_ms,
                "sandbox_version": "python-3.13",
            }
            report_submitted.set()
            with daemon._lock:
                daemon._inflight.discard(task.task_id)
            return report

        with (
            patch("evolver.gep.validator._poll_tasks", return_value=[fake_task]) as mock_poll,
            patch("evolver.gep.validator._claim_task", return_value=True) as mock_claim,
            patch.object(daemon, "_run_task", side_effect=fake_run_task),
        ):
            # Trigger a single tick manually
            daemon._tick()
            assert run_started.wait(timeout=2.0), "_run_task was not invoked"
            assert report_submitted.wait(timeout=2.0), "Report was not submitted"

        mock_poll.assert_called_once()
        mock_claim.assert_called_once_with("t1")
        daemon.stop()

    def test_failed_task_submits_failed_report(self):
        daemon = ValidatorDaemon(poll_interval=60.0)
        daemon.start()

        fake_task = self._make_fake_task("t2", "raise ValueError('boom')")
        report_submitted = threading.Event()
        captured_report: dict | None = None

        def fake_run_task(task):
            with daemon._lock:
                daemon._inflight.add(task.task_id)
            report = {
                "task_id": task.task_id,
                "status": "failed",
                "score": 0.0,
                "execution_log": "boom",
                "execution_time_ms": 10.0,
                "sandbox_version": "python-3.13",
            }
            nonlocal captured_report
            captured_report = report
            report_submitted.set()
            with daemon._lock:
                daemon._inflight.discard(task.task_id)
            return report

        with (
            patch("evolver.gep.validator._poll_tasks", return_value=[fake_task]),
            patch("evolver.gep.validator._claim_task", return_value=True),
            patch.object(daemon, "_run_task", side_effect=fake_run_task),
        ):
            daemon._tick()
            assert report_submitted.wait(timeout=2.0)

        assert captured_report is not None
        assert captured_report["status"] == "failed"
        assert captured_report["score"] == 0.0
        daemon.stop()

    def test_claim_failure_does_not_execute(self):
        daemon = ValidatorDaemon(poll_interval=60.0)
        daemon.start()

        fake_task = self._make_fake_task("t3")
        run_started = threading.Event()

        def fake_run_task(task):
            run_started.set()

        with (
            patch("evolver.gep.validator._poll_tasks", return_value=[fake_task]),
            patch("evolver.gep.validator._claim_task", return_value=False),
            patch("evolver.gep.validator.sandbox_executor.execute_in_sandbox") as mock_execute,
            patch("evolver.gep.validator.reporter.submit_report") as mock_submit,
            patch.object(daemon, "_run_task", side_effect=fake_run_task),
        ):
            daemon._tick()
            time.sleep(0.1)

        mock_execute.assert_not_called()
        mock_submit.assert_not_called()
        assert not run_started.is_set()
        daemon.stop()

    def test_concurrency_limit(self):
        daemon = ValidatorDaemon(poll_interval=60.0, max_concurrent=1)
        daemon.start()

        task_a = self._make_fake_task("a", "print('a')")
        task_b = self._make_fake_task("b", "print('b')")

        started_tasks: list[str] = []
        task_started = threading.Event()
        task_continue = threading.Event()

        def slow_run_task(task):
            with daemon._lock:
                daemon._inflight.add(task.task_id)
                started_tasks.append(task.task_id)
            task_started.set()
            task_continue.wait(timeout=2.0)
            with daemon._lock:
                daemon._inflight.discard(task.task_id)

        with (
            patch("evolver.gep.validator._poll_tasks", return_value=[task_a, task_b]),
            patch("evolver.gep.validator._claim_task", return_value=True),
            patch.object(daemon, "_run_task", side_effect=slow_run_task),
        ):
            daemon._tick()
            assert task_started.wait(timeout=2.0)
            # At this point one task should have started; second should be blocked by max_concurrent
            time.sleep(0.05)
            task_continue.set()

        # With max_concurrent=1 only one task should have started
        assert len(started_tasks) == 1
        daemon.stop()


class TestMapStatus:
    def test_passed(self):
        from evolver.gep.validator import _map_status

        result = SandboxResult(exit_code=0, stdout="", stderr="", timed_out=False, elapsed_ms=0.0)
        assert _map_status(result) == "passed"

    def test_failed(self):
        from evolver.gep.validator import _map_status

        result = SandboxResult(exit_code=1, stdout="", stderr="", timed_out=False, elapsed_ms=0.0)
        assert _map_status(result) == "failed"

    def test_timeout(self):
        from evolver.gep.validator import _map_status

        result = SandboxResult(exit_code=-1, stdout="", stderr="", timed_out=True, elapsed_ms=0.0)
        assert _map_status(result) == "timeout"


class TestLoopBackoff:
    def test_exponential_backoff_on_tick_error(self):
        daemon = ValidatorDaemon(poll_interval=60.0)

        call_count = 0

        def failing_tick():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("boom")
            # Third tick succeeds; stop daemon to avoid long poll wait
            daemon.stop()

        with patch.object(daemon, "_tick", side_effect=failing_tick):
            daemon.start()
            assert _wait_for(lambda: call_count >= 3, timeout=5.0)

        assert call_count >= 3


class TestSingleton:
    def test_start_stop_validator(self):
        from evolver.gep.validator import start_validator, stop_validator

        daemon = start_validator()
        assert daemon.is_running()
        stop_validator()
        assert not daemon.is_running()
