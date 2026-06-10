"""SQLite-backed event store — drop-in replacement for JSONL event storage.

Enabled via ``EVOLVER_SQLITE_STORE=1``.
Schema: a single ``events`` table with id/timestamp/data columns.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any


def _db_path() -> Path:
    home = Path(os.environ.get("EVOLVER_HOME", Path.home() / ".evolver"))
    return home / "evolver.db"


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT,
            timestamp TEXT,
            data TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp)"
    )
    conn.commit()


def append_event(record: dict[str, Any]) -> None:
    """Insert a single event record into SQLite."""
    db = _db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db), timeout=5.0) as conn:
        _ensure_table(conn)
        conn.execute(
            "INSERT INTO events (event_id, timestamp, data) VALUES (?, ?, ?)",
            (
                record.get("id") or record.get("event_id"),
                record.get("timestamp"),
                json.dumps(record, ensure_ascii=False),
            ),
        )
        conn.commit()


def read_events(limit: int = 10_000) -> list[dict[str, Any]]:
    """Read events ordered by insertion, newest last."""
    db = _db_path()
    if not db.exists():
        return []
    with sqlite3.connect(str(db), timeout=5.0) as conn:
        _ensure_table(conn)
        cursor = conn.execute(
            "SELECT data FROM events ORDER BY id ASC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
    return [json.loads(r[0]) for r in rows]


def read_all_events() -> list[dict[str, Any]]:
    """Read all events (up to a safe limit)."""
    return read_events(limit=100_000)


def event_count() -> int:
    db = _db_path()
    if not db.exists():
        return 0
    with sqlite3.connect(str(db), timeout=5.0) as conn:
        _ensure_table(conn)
        cursor = conn.execute("SELECT COUNT(*) FROM events")
        return cursor.fetchone()[0]


def read_events_range(start_ts: str, end_ts: str) -> list[dict[str, Any]]:
    """Read events whose timestamp falls within [start_ts, end_ts]."""
    db = _db_path()
    if not db.exists():
        return []
    with sqlite3.connect(str(db), timeout=5.0) as conn:
        _ensure_table(conn)
        cursor = conn.execute(
            "SELECT data FROM events WHERE timestamp >= ? AND timestamp <= ? ORDER BY id ASC",
            (start_ts, end_ts),
        )
        rows = cursor.fetchall()
    return [json.loads(r[0]) for r in rows]


def read_events_replay(since_id: int, limit: int = 100) -> list[dict[str, Any]]:
    """Replay events inserted after a given row id."""
    db = _db_path()
    if not db.exists():
        return []
    with sqlite3.connect(str(db), timeout=5.0) as conn:
        _ensure_table(conn)
        cursor = conn.execute(
            "SELECT data FROM events WHERE id > ? ORDER BY id ASC LIMIT ?",
            (since_id, limit),
        )
        rows = cursor.fetchall()
    return [json.loads(r[0]) for r in rows]
