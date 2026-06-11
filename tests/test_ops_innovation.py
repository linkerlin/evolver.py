"""Tests for ops/innovation.py.

Equivalent test source: test/innovation.test.js.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evolver.ops.innovation import (
    compute_innovation_roi,
    get_innovation_summary,
    record_innovation_attempt,
    record_innovation_outcome,
)


@pytest.fixture
def isolated_innovation_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log_path = tmp_path / "innovation_log.jsonl"
    monkeypatch.setenv("EVOLVER_INNOVATION_LOG_PATH", str(log_path))
    return log_path


class TestRecordInnovation:
    def test_record_attempt(self, isolated_innovation_log: Path) -> None:
        event = record_innovation_attempt(
            gene_id="gene_abc", strategy="innovate", hypothesis="test"
        )
        assert event["kind"] == "attempt"
        assert event["gene_id"] == "gene_abc"
        assert event["strategy"] == "innovate"
        assert isolated_innovation_log.exists()

    def test_record_outcome(self, isolated_innovation_log: Path) -> None:
        attempt = record_innovation_attempt(gene_id="gene_abc")
        outcome = record_innovation_outcome(
            attempt_id=attempt["id"],
            gene_id="gene_abc",
            status="success",
            score=0.85,
            capsule_id="cap_123",
        )
        assert outcome["kind"] == "outcome"
        assert outcome["status"] == "success"
        assert outcome["attempt_id"] == attempt["id"]


class TestComputeInnovationRoi:
    def test_insufficient_data(self, isolated_innovation_log: Path) -> None:
        roi = compute_innovation_roi(window_days=30, min_attempts=3)
        assert roi["insufficient_data"] is True
        assert roi["roi"] is None

    def test_roi_calculation(self, isolated_innovation_log: Path) -> None:
        # 4 attempts, 2 successes → ROI = 0.5
        for i in range(4):
            attempt = record_innovation_attempt(strategy="innovate")
            status = "success" if i < 2 else "failed"
            record_innovation_outcome(
                attempt_id=attempt["id"],
                status=status,
                score=0.8 if status == "success" else 0.2,
            )
        roi = compute_innovation_roi(window_days=30, min_attempts=3)
        assert roi["insufficient_data"] is False
        assert roi["total_attempts"] == 4
        assert roi["successful"] == 2
        assert roi["failed"] == 2
        assert roi["roi"] == 0.5

    def test_outside_window_ignored(
        self, isolated_innovation_log: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Write an old event directly
        old_event = {
            "type": "InnovationEvent",
            "kind": "attempt",
            "ts": "2020-01-01T00:00:00.000Z",
        }
        isolated_innovation_log.write_text(json.dumps(old_event) + "\n", encoding="utf-8")

        roi = compute_innovation_roi(window_days=1, min_attempts=1)
        assert roi["total_attempts"] == 0
        assert roi["insufficient_data"] is True


class TestGetInnovationSummary:
    def test_summary_structure(self, isolated_innovation_log: Path) -> None:
        summary = get_innovation_summary()
        assert "last_7d" in summary
        assert "last_30d" in summary
        assert "last_90d" in summary
        assert "recommendation" in summary
        assert summary["recommendation"] == "insufficient_data"
