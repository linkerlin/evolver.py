"""Tests for Sprint 7 missing modules — token_savings, narrative_memory,
memory_graph_adapter, directory_client, oauth_login, claim_nudge,
device_id, anti_abuse_telemetry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import evolver.gep.claim_nudge as cn
from evolver.gep import (
    anti_abuse_telemetry,
    device_id,
    narrative_memory,
    token_savings,
)
from evolver.gep.memory_graph_adapter import (
    fuzzy_signal_match,
    get_failure_pattern,
    get_success_trajectory,
    query_by_outcome,
    query_by_signal,
)

# ---------------------------------------------------------------------------
# token_savings
# ---------------------------------------------------------------------------


class TestTokenSavings:
    def test_compute_savings(self) -> None:
        result = token_savings.compute_savings(10000, 6000, "claude-3-5-sonnet")
        assert result["saved_tokens"] == 4000
        assert result["saved_cost_usd"] > 0

    def test_no_savings(self) -> None:
        result = token_savings.compute_savings(5000, 5000)
        assert result["saved_tokens"] == 0
        assert result["saved_cost_usd"] == 0

    def test_get_model_pricing(self) -> None:
        p = token_savings.get_model_pricing("gpt-4o")
        assert p["input"] == 2.5

    def test_tracker_record_and_summary(self, tmp_path: Path) -> None:
        tracker = token_savings.SavingsTracker(tmp_path / "savings.json")
        tracker.record(10000, 5000, "claude-3-5-sonnet")
        tracker.record(8000, 6000, "claude-3-5-sonnet")
        summary = tracker.get_summary()
        assert summary["cycles"] == 2
        assert summary["total_saved_tokens"] == 7000

    def test_generate_report(self, tmp_path: Path) -> None:
        tracker = token_savings.SavingsTracker(tmp_path / "savings.json")
        tracker.record(10000, 5000)
        report = tracker.generate_report()
        assert "Token Savings Report" in report
        assert "5,000" in report  # saved tokens


# ---------------------------------------------------------------------------
# narrative_memory
# ---------------------------------------------------------------------------


class TestNarrativeMemory:
    def test_empty_events(self) -> None:
        result = narrative_memory.build_narrative([])
        assert "No evolution events" in result

    def test_with_events(self) -> None:
        events = [
            {
                "category": "repair",
                "outcome": {"status": "success", "score": 0.9},
                "signals": ["log_error", "test_failure"],
                "gene_id": "gene_repair",
            },
            {
                "category": "optimize",
                "outcome": {"status": "failed", "score": 0.3},
                "signals": ["perf_bottleneck"],
                "gene_id": "gene_optimize",
            },
        ]
        result = narrative_memory.build_narrative(events)
        assert "2 recent events" in result
        assert "50% success" in result
        assert "repair: 1" in result

    def test_load_events(self, tmp_path: Path) -> None:
        p = tmp_path / "events.jsonl"
        p.write_text('{"a": 1}\n{"b": 2}\n', encoding="utf-8")
        events = narrative_memory.load_events(p)
        assert len(events) == 2


# ---------------------------------------------------------------------------
# memory_graph_adapter
# ---------------------------------------------------------------------------


class TestMemoryGraphAdapter:
    def setup_method(self) -> None:
        self.entries = [
            {"signals": ["log_error"], "outcome": {"status": "success", "score": 0.9}},
            {
                "signals": ["log_error"],
                "outcome": {"status": "failed", "score": 0.2, "note": "timeout"},
            },
            {"signals": ["perf_bottleneck"], "outcome": {"status": "success", "score": 0.8}},
        ]

    def test_query_by_signal(self) -> None:
        result = query_by_signal(self.entries, "log_error")
        assert len(result) == 2

    def test_query_by_outcome(self) -> None:
        result = query_by_outcome(self.entries, "success", min_score=0.5)
        assert len(result) == 2

    def test_success_trajectory(self) -> None:
        result = get_success_trajectory(self.entries, "log_error")
        assert len(result) == 1
        assert result[0]["outcome"]["status"] == "success"

    def test_failure_pattern(self) -> None:
        result = get_failure_pattern(self.entries, "log_error")
        assert result["total_failures"] == 1
        assert result["total_entries"] == 2
        assert result["failure_rate"] == 0.5

    def test_fuzzy_match(self) -> None:
        result = fuzzy_signal_match(self.entries, "log_eror", max_distance=2)
        assert len(result) >= 1  # "log_eror" ~ "log_error"


# ---------------------------------------------------------------------------
# claim_nudge
# ---------------------------------------------------------------------------


class TestClaimNudge:
    def test_build_nudge_with_tasks(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(cn, "_nudge_state_path", lambda: tmp_path / "nudge.json")
        cn.reset_nudge()
        result = cn.build_nudge(3, {"task_id": "t1", "bounty": 5.0})
        assert result is not None
        assert "3 task(s)" in result

    def test_no_nudge_for_zero_tasks(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(cn, "_nudge_state_path", lambda: tmp_path / "nudge.json")
        cn.reset_nudge()
        assert cn.build_nudge(0) is None

    def test_cooldown_prevents_repeat(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(cn, "_nudge_state_path", lambda: tmp_path / "nudge.json")
        cn.reset_nudge()
        first = cn.build_nudge(5)
        assert first is not None
        second = cn.build_nudge(5)
        assert second is None  # cooldown


# ---------------------------------------------------------------------------
# device_id
# ---------------------------------------------------------------------------


class TestDeviceId:
    def test_stable_across_calls(self) -> None:
        id1 = device_id.get_device_id()
        id2 = device_id.get_device_id()
        assert id1 == id2
        assert len(id1) == 32

    def test_fingerprint(self) -> None:
        fp = device_id.get_device_fingerprint()
        assert "device_id" in fp
        assert "platform" in fp
        assert len(fp["device_id"]) == 32


# ---------------------------------------------------------------------------
# anti_abuse_telemetry
# ---------------------------------------------------------------------------


class TestAbuseDetector:
    def test_clean_start(self, tmp_path: Path) -> None:
        detector = anti_abuse_telemetry.AbuseDetector(tmp_path / "abuse.jsonl")
        assert detector.get_score() < 0.7

    def test_flood_detection(self, tmp_path: Path) -> None:
        detector = anti_abuse_telemetry.AbuseDetector(tmp_path / "abuse.jsonl")
        for _ in range(25):
            detector.record_gene_creation()
        assert detector.get_score() >= 0.7

    def test_idle_cycles(self, tmp_path: Path) -> None:
        detector = anti_abuse_telemetry.AbuseDetector(tmp_path / "abuse.jsonl")
        for _ in range(60):
            detector.record_idle_cycle()
        assert detector.get_score() >= 0.7

    def test_reset_progress(self, tmp_path: Path) -> None:
        detector = anti_abuse_telemetry.AbuseDetector(tmp_path / "abuse.jsonl")
        for _ in range(40):
            detector.record_idle_cycle()
        detector.reset_progress()
        assert detector.get_score() < 0.7

    def test_validation_skip(self, tmp_path: Path) -> None:
        detector = anti_abuse_telemetry.AbuseDetector(tmp_path / "abuse.jsonl")
        for _ in range(6):
            detector.record_validation_skip()
        assert detector.get_score() >= 0.7

    def test_writes_log(self, tmp_path: Path) -> None:
        log = tmp_path / "abuse.jsonl"
        detector = anti_abuse_telemetry.AbuseDetector(log)
        for _ in range(25):
            detector.record_gene_creation()
        assert log.exists()
        content = log.read_text(encoding="utf-8")
        assert "gene_flood" in content
