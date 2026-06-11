"""Tests for evolver.gep.issue_reporter."""

import json
from unittest.mock import MagicMock, patch

import pytest

from evolver.gep.issue_reporter import (
    FAILURE_THRESHOLD,
    IssueDraft,
    _count_failures_by_signal,
    _load_cache,
    _save_cache,
    _sanitise,
    report_recurring_failures,
    should_report,
)


class TestSanitise:
    def test_redacts_token(self):
        text = "Authorization: Bearer sk-1234567890abcdef"
        result = _sanitise(text)
        assert "<REDACTED>" in result
        assert "sk-1234567890abcdef" not in result

    def test_redacts_home_dir(self):
        import os
        home = os.path.expanduser("~")
        text = f"path: {home}/project/file.py"
        result = _sanitise(text)
        assert home not in result
        assert "~" in result

    def test_redacts_username_windows(self):
        text = "C:\\Users\\john\\project\\file.py"
        result = _sanitise(text)
        assert "john" not in result
        assert "<USER>" in result


class TestCountFailures:
    def test_counts_failures(self):
        now = 1000100
        events = [
            {"type": "attempt", "timestamp": 1000000, "outcome": "failure", "signals_snapshot": ["auth"]},
            {"type": "attempt", "timestamp": 1000001, "outcome": "failure", "signals_snapshot": ["auth"]},
            {"type": "attempt", "timestamp": 1000002, "outcome": "failure", "signals_snapshot": ["auth"]},
            {"type": "attempt", "timestamp": 1000003, "outcome": "success", "signals_snapshot": ["auth"]},
        ]
        counts = _count_failures_by_signal(events, window_seconds=10000, now=now)
        assert len(counts) == 1
        assert list(counts.values())[0] == 3

    def test_ignores_success(self):
        now = 1000100
        events = [
            {"type": "attempt", "timestamp": 1000000, "outcome": "success", "signals_snapshot": ["auth"]},
        ]
        counts = _count_failures_by_signal(events, now=now)
        assert counts == {}

    def test_outside_window_ignored(self):
        now = 1000100
        events = [
            {"type": "attempt", "timestamp": 0, "outcome": "failure", "signals_snapshot": ["auth"]},
        ]
        counts = _count_failures_by_signal(events, window_seconds=100, now=now)
        assert counts == {}


class TestCache:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "cache.json"
        cache = {"abc": 1000.0}
        _save_cache(cache, path=path)
        loaded = _load_cache(path=path)
        assert loaded == cache

    def test_missing(self, tmp_path):
        assert _load_cache(path=tmp_path / "missing.json") == {}


class TestReportRecurringFailures:
    def test_no_token_no_crash(self, tmp_path):
        events = [
            {"type": "attempt", "timestamp": 1000000, "outcome": "failure", "signals_snapshot": ["auth"], "error": "timeout"},
        ] * 3
        with patch.dict("os.environ", {}, clear=True):
            with patch("evolver.gep.issue_reporter._repo_from_git", return_value=None):
                urls = report_recurring_failures(events=events, cache_path=tmp_path / "cache.json")
        assert urls == []

    def test_below_threshold(self, tmp_path):
        events = [
            {"type": "attempt", "timestamp": 1000000, "outcome": "failure", "signals_snapshot": ["auth"]},
        ] * 2
        urls = report_recurring_failures(events=events, cache_path=tmp_path / "cache.json")
        assert urls == []

    def test_cooldown(self, tmp_path):
        events = [
            {"type": "attempt", "timestamp": 1000000, "outcome": "failure", "signals_snapshot": ["auth"], "error": "err"},
        ] * 3
        path = tmp_path / "cache.json"
        report_recurring_failures(events=events, cache_path=path)
        # Second call should be in cooldown
        urls = report_recurring_failures(events=events, cache_path=path)
        assert urls == []


class TestShouldReport:
    def test_new_signal(self):
        assert should_report("new_signal")

    def test_in_cooldown(self, tmp_path):
        cache = {"sig": time.time()}
        _save_cache(cache, path=tmp_path / "cache.json")
        assert not should_report("sig", cache_path=tmp_path / "cache.json")

    def test_expired_cooldown(self, tmp_path):
        cache = {"sig": time.time() - 8 * 86400}
        _save_cache(cache, path=tmp_path / "cache.json")
        assert should_report("sig", cache_path=tmp_path / "cache.json")


import time
