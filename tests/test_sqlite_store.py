"""Tests for evolver.ops.sqlite_store."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.ops import sqlite_store


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evolver"))


class TestSQLiteStore:
    def test_empty(self) -> None:
        assert sqlite_store.read_all_events() == []
        assert sqlite_store.event_count() == 0

    def test_append_and_read(self) -> None:
        sqlite_store.append_event(
            {"id": "e1", "timestamp": "2024-01-01T00:00:00Z", "gene_id": "g1"}
        )
        sqlite_store.append_event(
            {"id": "e2", "timestamp": "2024-01-01T00:01:00Z", "gene_id": "g2"}
        )
        events = sqlite_store.read_all_events()
        assert len(events) == 2
        assert events[0]["id"] == "e1"
        assert events[1]["id"] == "e2"
        assert sqlite_store.event_count() == 2

    def test_large_payload(self) -> None:
        big = {"id": "e3", "data": "x" * 10_000}
        sqlite_store.append_event(big)
        events = sqlite_store.read_all_events()
        assert events[0]["data"] == "x" * 10_000

    def test_limit(self) -> None:
        for i in range(5):
            sqlite_store.append_event({"id": f"e{i}"})
        events = sqlite_store.read_events(limit=3)
        assert len(events) == 3
        assert events[-1]["id"] == "e2"


class TestAssetStoreRouting:
    def test_jsonl_by_default(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
        from evolver.gep.asset_store import append_event_jsonl, read_all_events

        append_event_jsonl({"id": "x1", "timestamp": "t1"})
        events = read_all_events()
        assert any(e.get("id") == "x1" for e in events)

    def test_sqlite_when_enabled(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("EVOLUTION_DIR", str(tmp_path / "evolution"))
        monkeypatch.setenv("EVOLVER_HOME", str(tmp_path / ".evolver"))
        monkeypatch.setenv("EVOLVER_SQLITE_STORE", "1")
        from evolver.gep.asset_store import append_event_jsonl, read_all_events

        append_event_jsonl({"id": "x2", "timestamp": "t2"})
        events = read_all_events()
        assert any(e.get("id") == "x2" for e in events)
        assert sqlite_store.event_count() >= 1
