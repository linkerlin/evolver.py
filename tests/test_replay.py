"""Tests for SQLite event replay."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.ops import sqlite_store


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evolver"))


class TestReplay:
    def test_replay_since_id(self) -> None:
        for i in range(5):
            sqlite_store.append_event({"id": f"e{i}", "timestamp": f"2024-01-01T00:0{i}:00Z"})
        events = sqlite_store.read_events_replay(since_id=2, limit=10)
        assert len(events) == 3
        assert events[0]["id"] == "e2"

    def test_replay_limit(self) -> None:
        for i in range(10):
            sqlite_store.append_event({"id": f"e{i}"})
        events = sqlite_store.read_events_replay(since_id=0, limit=3)
        assert len(events) == 3

    def test_range_query(self) -> None:
        sqlite_store.append_event({"id": "a", "timestamp": "2024-01-01T10:00:00Z"})
        sqlite_store.append_event({"id": "b", "timestamp": "2024-01-01T12:00:00Z"})
        sqlite_store.append_event({"id": "c", "timestamp": "2024-01-01T14:00:00Z"})
        events = sqlite_store.read_events_range("2024-01-01T11:00:00Z", "2024-01-01T13:00:00Z")
        assert len(events) == 1
        assert events[0]["id"] == "b"


