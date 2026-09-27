"""Tests for evolver.gep.cursor (charter 配对会话 §5.5).

The cursor is where external experience has been consumed up to. It advances
in exactly one place — the Accept — and the trigger that reads it only ever
reminds. Two properties matter more than the rest: a Reject must not consume
experience, and the reminder must never start anything.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from evolver.gep import cursor as cursor_mod


@pytest.fixture
def cursor_env(temp_workspace: Path) -> Path:
    return temp_workspace


def test_no_cursor_yet(cursor_env: Path) -> None:
    assert cursor_mod.load_cursor() is None
    # Anchored on nothing, the reminder has no age to compare.
    assert cursor_mod.reminder()["age_days"] is None


def test_first_advance_writes_the_cursor(cursor_env: Path) -> None:
    result = cursor_mod.advance(recorded_at="2026-09-26T10:00:00Z", session_id="s1")
    assert result["ok"] is True
    assert cursor_mod.load_cursor()["checkpoint_session"] == "s1"


def test_an_older_stamp_does_not_move_the_cursor(cursor_env: Path) -> None:
    cursor_mod.advance(recorded_at="2026-09-26T10:00:00Z", session_id="s1")
    result = cursor_mod.advance(recorded_at="2026-09-20T10:00:00Z", session_id="s0")
    assert result["ok"] is False
    assert result["reason"] == cursor_mod.REASON_NOT_NEWER
    assert cursor_mod.load_cursor()["checkpoint_session"] == "s1"


def test_an_equal_stamp_does_not_move_the_cursor(cursor_env: Path) -> None:
    """Strict: re-Accepting the same moment must not consume the same
    experience twice."""
    cursor_mod.advance(recorded_at="2026-09-26T10:00:00Z", session_id="s1")
    result = cursor_mod.advance(recorded_at="2026-09-26T10:00:00Z", session_id="s1")
    assert result["ok"] is False
    assert result["reason"] == cursor_mod.REASON_NOT_NEWER


def test_same_second_sessions_stay_ordered(cursor_env: Path) -> None:
    """The source compares times only, which loses ordering inside a second.
    evolver compares (time, session) so the later session still wins."""
    cursor_mod.advance(recorded_at="2026-09-26T10:00:00Z", session_id="s1")
    result = cursor_mod.advance(recorded_at="2026-09-26T10:00:00Z", session_id="s2")
    assert result["ok"] is True
    assert cursor_mod.load_cursor()["checkpoint_session"] == "s2"


def test_is_after_needs_a_strictly_newer_tuple(cursor_env: Path) -> None:
    point = {"checkpoint_time": "2026-09-26T10:00:00Z", "checkpoint_session": "s1"}
    assert cursor_mod.is_after(point, "2026-09-26T11:00:00Z", "s0") is True
    assert cursor_mod.is_after(point, "2026-09-26T10:00:00Z", "s2") is True
    assert cursor_mod.is_after(point, "2026-09-26T10:00:00Z", "s1") is False
    assert cursor_mod.is_after(point, "2026-09-25T10:00:00Z", "s9") is False


def test_trajectory_counter_accumulates(cursor_env: Path) -> None:
    cursor_mod.advance(recorded_at="2026-09-26T10:00:00Z", session_id="s1")
    cursor_mod.record_trajectory()
    cursor_mod.record_trajectory(2)
    assert int(cursor_mod.load_cursor()["trajectories_seen_since"]) == 3


def test_reminder_fires_on_age(cursor_env: Path) -> None:
    cursor_mod.advance(recorded_at="2026-01-01T00:00:00Z", session_id="s1")
    now = datetime(2026, 9, 26, tzinfo=UTC)
    result = cursor_mod.reminder(now=now)
    assert result["due"] is True
    assert result["by_age"] is True
    assert result["by_trajectory"] is False


def test_reminder_fires_on_trajectory_count(cursor_env: Path) -> None:
    cursor_mod.advance(recorded_at="2026-09-26T00:00:00Z", session_id="s1")
    for _ in range(cursor_mod.CURSOR_MIN_TRAJECTORIES):
        cursor_mod.record_trajectory()
    result = cursor_mod.reminder(now=datetime(2026, 9, 26, 12, tzinfo=UTC))
    assert result["due"] is True
    assert result["by_trajectory"] is True


def test_reminder_is_quiet_when_nothing_piled_up(cursor_env: Path) -> None:
    cursor_mod.advance(recorded_at="2026-09-26T00:00:00Z", session_id="s1")
    result = cursor_mod.reminder(now=datetime(2026, 9, 27, tzinfo=UTC))
    assert result["due"] is False


def test_the_reminder_never_moves_the_cursor(cursor_env: Path) -> None:
    """The whole point of §5.5: the trigger reminds, it does not act."""
    cursor_mod.advance(recorded_at="2026-01-01T00:00:00Z", session_id="s1")
    before = cursor_mod.load_cursor()
    cursor_mod.reminder(now=datetime(2026, 9, 26, tzinfo=UTC))
    after = cursor_mod.load_cursor()
    assert before["checkpoint_session"] == after["checkpoint_session"]
    assert before["checkpoint_time"] == after["checkpoint_time"]


def test_a_damaged_cursor_reads_as_no_cursor(cursor_env: Path) -> None:
    cursor_mod.cursor_path().parent.mkdir(parents=True, exist_ok=True)
    cursor_mod.cursor_path().write_text("{ not json", encoding="utf-8")
    assert cursor_mod.load_cursor() is None
    # Anchored on nothing, the first advance is still allowed.
    assert cursor_mod.advance(recorded_at="2026-09-26T10:00:00Z", session_id="s1")["ok"] is True


def test_age_is_measured_in_days(cursor_env: Path) -> None:
    stamp = datetime(2026, 9, 19, tzinfo=UTC)
    cursor_mod.advance(recorded_at=stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), session_id="s1")
    result = cursor_mod.reminder(now=stamp + timedelta(days=7))
    assert result["age_days"] == 7.0
