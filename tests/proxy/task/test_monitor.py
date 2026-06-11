"""Tests for evolver.proxy.task.monitor."""

from __future__ import annotations

from evolver.proxy.task.monitor import InMemoryTaskStore, TaskMonitor


class TestInMemoryTaskStore:
    def test_get_set(self):
        store = InMemoryTaskStore()
        assert store.get("x") is None
        store.set("x", "hello")
        assert store.get("x") == "hello"


class TestTaskMonitor:
    def test_initial_state(self):
        monitor = TaskMonitor()
        assert monitor.subscribed is False
        metrics = monitor.get_metrics()
        assert metrics["tasks_received"] == 0
        assert metrics["tasks_claimed"] == 0

    def test_subscribe_unsubscribe(self):
        monitor = TaskMonitor()
        result = monitor.subscribe(filters=["auth"])
        assert result["subscribed"] is True
        assert monitor.subscribed is True

        result = monitor.unsubscribe()
        assert result["subscribed"] is False
        assert monitor.subscribed is False

    def test_record_claim(self):
        monitor = TaskMonitor()
        monitor.record_claim("t1")
        metrics = monitor.get_metrics()
        assert metrics["tasks_claimed"] == 1
        assert metrics["last_claim_at"] is not None

    def test_record_complete(self):
        monitor = TaskMonitor()
        monitor.record_complete("t1", started_at=0.0)
        metrics = monitor.get_metrics()
        assert metrics["tasks_completed"] == 1
        assert metrics["avg_completion_ms"] > 0

    def test_record_failed(self):
        monitor = TaskMonitor()
        monitor.record_failed("t1")
        metrics = monitor.get_metrics()
        assert metrics["tasks_failed"] == 1

    def test_record_received(self):
        monitor = TaskMonitor()
        monitor.record_received(5)
        metrics = monitor.get_metrics()
        assert metrics["tasks_received"] == 5

    def test_heartbeat_meta(self):
        monitor = TaskMonitor()
        meta = monitor.get_heartbeat_meta()
        assert "task_subscription" in meta
        assert "task_metrics" in meta

    def test_persistence(self):
        monitor = TaskMonitor()
        monitor.record_claim("t1")
        monitor.record_complete("t1", started_at=0.0)

        # Create a new monitor with the same store
        new_monitor = TaskMonitor(store=monitor.store)
        metrics = new_monitor.get_metrics()
        assert metrics["tasks_claimed"] == 1
        assert metrics["tasks_completed"] == 1

    def test_avg_completion_rolling_window(self):
        monitor = TaskMonitor()
        for i in range(105):
            monitor.record_complete(f"t{i}", started_at=0.0)
        metrics = monitor.get_metrics()
        # Should only keep last 100
        assert len(monitor._stats["_completion_times"]) == 100
        assert metrics["avg_completion_ms"] > 0
