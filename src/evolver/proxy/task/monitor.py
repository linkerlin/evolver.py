"""Task monitor — track task lifecycle metrics and subscription state.

Equivalent to evolver/src/proxy/task/monitor.js.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class _StoreLike(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any) -> None: ...


class InMemoryTaskStore:
    """Simple in-memory store for task monitor state."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def get(self, key: str) -> Any | None:
        return self._data.get(key)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value


def _default_store() -> _StoreLike:
    return InMemoryTaskStore()


class TaskMonitor:
    """Track task metrics: received, claimed, completed, failed."""

    def __init__(self, store: _StoreLike | None = None) -> None:
        self.store = store or _default_store()
        self._stats: dict[str, Any] = {
            "tasks_received": 0,
            "tasks_claimed": 0,
            "tasks_completed": 0,
            "tasks_failed": 0,
            "last_claim_at": None,
            "last_complete_at": None,
            "avg_completion_ms": 0.0,
            "_completion_times": [],
        }
        self._restore_stats()

    def _restore_stats(self) -> None:
        raw = self.store.get("task_monitor_stats")
        if raw is None:
            return
        try:
            saved = json.loads(raw) if isinstance(raw, str) else raw
            for key in ("tasks_claimed", "tasks_completed", "tasks_failed", "tasks_received"):
                if key in saved:
                    self._stats[key] = saved[key]
            for key in ("last_claim_at", "last_complete_at"):
                if key in saved:
                    self._stats[key] = saved[key]
            if "avg_completion_ms" in saved:
                self._stats["avg_completion_ms"] = saved["avg_completion_ms"]
        except (json.JSONDecodeError, TypeError):
            logger.debug("[TaskMonitor] Ignoring corrupt stored stats")

    @property
    def subscribed(self) -> bool:
        raw = self.store.get("task_subscription")
        if raw is None:
            return False
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            return bool(parsed.get("enabled"))
        except (json.JSONDecodeError, TypeError):
            return False

    def subscribe(self, filters: list[str] | None = None) -> dict[str, Any]:
        payload = {
            "enabled": True,
            "filters": filters or [],
            "subscribed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.store.set("task_subscription", json.dumps(payload))
        logger.info("[TaskMonitor] Subscribed with filters: %s", filters)
        return {"ok": True, "subscribed": True, "filters": filters or []}

    def unsubscribe(self) -> dict[str, Any]:
        payload = {
            "enabled": False,
            "unsubscribed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.store.set("task_subscription", json.dumps(payload))
        logger.info("[TaskMonitor] Unsubscribed")
        return {"ok": True, "subscribed": False}

    def record_claim(self, task_id: str) -> None:
        self._stats["tasks_claimed"] += 1
        self._stats["last_claim_at"] = time.time()
        self._persist()

    def record_complete(self, task_id: str, started_at: float | None = None) -> None:
        self._stats["tasks_completed"] += 1
        self._stats["last_complete_at"] = time.time()
        if started_at is not None:
            duration = int((time.time() - started_at) * 1000)
            times: list[int] = self._stats["_completion_times"]
            times.append(duration)
            if len(times) > 100:
                times.pop(0)
            self._stats["avg_completion_ms"] = round(sum(times) / len(times), 1)
        self._persist()

    def record_failed(self, task_id: str) -> None:
        self._stats["tasks_failed"] += 1
        self._persist()

    def record_received(self, count: int = 1) -> None:
        self._stats["tasks_received"] += count

    def get_metrics(self) -> dict[str, Any]:
        return {
            "subscribed": self.subscribed,
            "tasks_received": self._stats["tasks_received"],
            "tasks_claimed": self._stats["tasks_claimed"],
            "tasks_completed": self._stats["tasks_completed"],
            "tasks_failed": self._stats["tasks_failed"],
            "last_claim_at": self._stats["last_claim_at"],
            "last_complete_at": self._stats["last_complete_at"],
            "avg_completion_ms": self._stats["avg_completion_ms"],
        }

    def get_heartbeat_meta(self) -> dict[str, Any]:
        return {
            "task_subscription": self.subscribed,
            "task_metrics": {
                "claimed": self._stats["tasks_claimed"],
                "completed": self._stats["tasks_completed"],
                "failed": self._stats["tasks_failed"],
                "avg_completion_ms": self._stats["avg_completion_ms"],
            },
        }

    def _persist(self) -> None:
        snapshot = {k: v for k, v in self._stats.items() if not k.startswith("_")}
        self.store.set("task_monitor_stats", json.dumps(snapshot))
