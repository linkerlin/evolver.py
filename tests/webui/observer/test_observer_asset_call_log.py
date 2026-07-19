"""Tests for evolver.webui.observer.asset_call_log."""

from __future__ import annotations

import json
from pathlib import Path

from evolver.webui.observer.asset_call_log import (
    call_log_summary,
    calls_by_run,
    cost_index,
    recent_calls,
    reuse_summary,
)


class TestCallLogSummary:
    def test_empty(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(
            "evolver.gep.asset_call_log.get_log_path",
            lambda: tmp_path / "asset_call_log.jsonl",
        )
        result = call_log_summary()
        assert result["total_entries"] == 0
        assert result["unique_assets"] == 0

    def test_with_entries(self, monkeypatch, tmp_path: Path):
        log = tmp_path / "asset_call_log.jsonl"
        entries = [
            {
                "asset_id": "a1",
                "action": "hub_search_hit",
                "run_id": "r1",
                "timestamp": "2025-01-01T00:00:00Z",
            },
            {
                "asset_id": "a2",
                "action": "asset_reuse",
                "run_id": "r1",
                "tokens_saved": 100,
                "timestamp": "2025-01-01T00:01:00Z",
            },
            {
                "asset_id": "a1",
                "action": "asset_reference",
                "run_id": "r2",
                "tokens_saved": 50,
                "timestamp": "2025-01-01T00:02:00Z",
            },
        ]
        log.write_text("\n".join(json.dumps(e) for e in entries))
        monkeypatch.setattr("evolver.gep.asset_call_log.get_log_path", lambda: log)
        result = call_log_summary()
        assert result["total_entries"] == 3
        assert result["unique_assets"] == 2
        assert result["unique_runs"] == 2

    def test_run_id_filter(self, monkeypatch, tmp_path: Path):
        log = tmp_path / "asset_call_log.jsonl"
        entries = [
            {
                "asset_id": "a1",
                "action": "hub_search_hit",
                "run_id": "r1",
                "timestamp": "2025-01-01T00:00:00Z",
            },
            {
                "asset_id": "a2",
                "action": "asset_reuse",
                "run_id": "r2",
                "timestamp": "2025-01-01T00:01:00Z",
            },
        ]
        log.write_text("\n".join(json.dumps(e) for e in entries))
        monkeypatch.setattr("evolver.gep.asset_call_log.get_log_path", lambda: log)
        result = call_log_summary(run_id="r1")
        assert result["total_entries"] == 1
        assert result["unique_assets"] == 1


class TestReuseSummary:
    def test_empty(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(
            "evolver.gep.asset_call_log.get_log_path",
            lambda: tmp_path / "asset_call_log.jsonl",
        )
        result = reuse_summary()
        assert result["total_reuse"] == 0
        assert result["total_tokens_saved"] == 0
        assert result["by_asset"] == []

    def test_with_reuse(self, monkeypatch, tmp_path: Path):
        log = tmp_path / "asset_call_log.jsonl"
        entries = [
            {
                "asset_id": "a1",
                "action": "asset_reuse",
                "tokens_saved": 200,
                "timestamp": "2025-01-01T00:00:00Z",
            },
            {
                "asset_id": "a1",
                "action": "asset_reference",
                "tokens_saved": 50,
                "timestamp": "2025-01-01T00:01:00Z",
            },
            {
                "asset_id": "a2",
                "action": "asset_reuse",
                "tokens_saved": 100,
                "timestamp": "2025-01-01T00:02:00Z",
            },
        ]
        log.write_text("\n".join(json.dumps(e) for e in entries))
        monkeypatch.setattr("evolver.gep.asset_call_log.get_log_path", lambda: log)
        result = reuse_summary()
        assert result["total_reuse"] == 2
        assert result["total_reference"] == 1
        assert result["total_tokens_saved"] == 350
        assert len(result["by_asset"]) == 2


class TestCostIndex:
    def test_empty(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(
            "evolver.gep.asset_call_log.get_log_path",
            lambda: tmp_path / "asset_call_log.jsonl",
        )
        result = cost_index()
        assert result == {}

    def test_with_costs(self, monkeypatch, tmp_path: Path):
        log = tmp_path / "asset_call_log.jsonl"
        entries = [
            {
                "asset_id": "a1",
                "action": "asset_publish",
                "tokens_spent": 500,
                "timestamp": "2025-01-01T00:00:00Z",
            },
            {
                "asset_id": "a2",
                "action": "asset_publish",
                "tokens_spent": 300,
                "timestamp": "2025-01-01T00:01:00Z",
            },
        ]
        log.write_text("\n".join(json.dumps(e) for e in entries))
        monkeypatch.setattr("evolver.gep.asset_call_log.get_log_path", lambda: log)
        result = cost_index()
        assert result == {"a1": 500, "a2": 300}


class TestRecentCalls:
    def test_empty(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(
            "evolver.gep.asset_call_log.get_log_path",
            lambda: tmp_path / "asset_call_log.jsonl",
        )
        result = recent_calls()
        assert result == []

    def test_with_entries(self, monkeypatch, tmp_path: Path):
        log = tmp_path / "asset_call_log.jsonl"
        entries = [
            {"asset_id": "a1", "action": "hub_search_hit", "timestamp": "2025-01-01T00:00:00Z"},
            {"asset_id": "a2", "action": "hub_search_miss", "timestamp": "2025-01-01T00:01:00Z"},
        ]
        log.write_text("\n".join(json.dumps(e) for e in entries))
        monkeypatch.setattr("evolver.gep.asset_call_log.get_log_path", lambda: log)
        result = recent_calls(last=1)
        assert len(result) == 1


class TestCallsByRun:
    def test_empty(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr(
            "evolver.gep.asset_call_log.get_log_path",
            lambda: tmp_path / "asset_call_log.jsonl",
        )
        result = calls_by_run("r1")
        assert result == []

    def test_with_run(self, monkeypatch, tmp_path: Path):
        log = tmp_path / "asset_call_log.jsonl"
        entries = [
            {
                "asset_id": "a1",
                "action": "hub_search_hit",
                "run_id": "r1",
                "timestamp": "2025-01-01T00:00:00Z",
            },
            {
                "asset_id": "a2",
                "action": "hub_search_miss",
                "run_id": "r2",
                "timestamp": "2025-01-01T00:01:00Z",
            },
        ]
        log.write_text("\n".join(json.dumps(e) for e in entries))
        monkeypatch.setattr("evolver.gep.asset_call_log.get_log_path", lambda: log)
        result = calls_by_run("r1")
        assert len(result) == 1
        assert result[0]["asset_id"] == "a1"
