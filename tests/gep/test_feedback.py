"""Unified evaluation feedback — EvoX concept harvest (v1.99.0).

Contract-only port of EvoX's EvaluationFeedback: primary_score / metrics /
textual_gradient three-way separation, journal + pending-signal injection.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from evolver.gep.feedback import (
    FEEDBACK_SIGNAL_DEGRADED,
    FEEDBACK_SIGNAL_OK,
    GRADIENT_SIGNAL_PREFIX,
    EvaluationFeedback,
    feedback_journal_path,
    load_recent_feedback,
    record_feedback,
)


class TestModel:
    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            EvaluationFeedback(primary_score=0.5, bogus=1)  # type: ignore[call-arg]

    def test_score_bounds(self) -> None:
        with pytest.raises(ValidationError):
            EvaluationFeedback(primary_score=1.5)
        with pytest.raises(ValidationError):
            EvaluationFeedback(primary_score=-0.1)

    def test_signal_keys_ok(self) -> None:
        fb = EvaluationFeedback(primary_score=0.9, success=True)
        assert fb.signal_keys() == [FEEDBACK_SIGNAL_OK]

    def test_signal_keys_degraded_with_gradient(self) -> None:
        fb = EvaluationFeedback(primary_score=0.2, textual_gradient="锚点定位失败，重试仍 flaky")
        keys = fb.signal_keys()
        assert keys[0] == FEEDBACK_SIGNAL_DEGRADED
        assert keys[1].startswith(GRADIENT_SIGNAL_PREFIX)
        assert "flaky" in keys[1]

    def test_gradient_signal_is_bounded(self) -> None:
        fb = EvaluationFeedback(primary_score=0.1, textual_gradient="长" * 500)
        gradient_key = fb.signal_keys()[1]
        assert len(gradient_key) <= len(GRADIENT_SIGNAL_PREFIX) + 1 + 120

    def test_failure_is_degraded_even_with_high_score(self) -> None:
        fb = EvaluationFeedback(primary_score=0.9, success=False)
        assert fb.signal_keys() == [FEEDBACK_SIGNAL_DEGRADED]

    def test_ok_report_carries_no_gradient_signal(self) -> None:
        fb = EvaluationFeedback(primary_score=0.95, textual_gradient="很顺利")
        assert fb.signal_keys() == [FEEDBACK_SIGNAL_OK]

    def test_threshold_is_consulted_at_call_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fb = EvaluationFeedback(primary_score=0.3)
        assert fb.is_degraded() is True
        monkeypatch.setattr("evolver.config.SWARM_FEEDBACK_DEGRADED_THRESHOLD", 0.1)
        assert fb.is_degraded() is False


class TestRecord:
    def test_record_journals_and_injects_signals(self, temp_workspace: Path) -> None:
        result = record_feedback(
            EvaluationFeedback(primary_score=0.3, textual_gradient="x did not help")
        )
        assert result["ok"] is True
        assert result["degraded"] is True
        assert FEEDBACK_SIGNAL_DEGRADED in result["injected_signals"]
        assert result["feedback_id"].startswith("fb_")

        from evolver.gep.asset_store import consume_pending_signals

        pending = consume_pending_signals()
        assert FEEDBACK_SIGNAL_DEGRADED in pending
        assert any(s.startswith(GRADIENT_SIGNAL_PREFIX) for s in pending)

        rows = load_recent_feedback()
        assert len(rows) == 1
        assert rows[0]["id"] == result["feedback_id"]
        assert rows[0]["primary_score"] == 0.3
        assert feedback_journal_path().exists()

    def test_pending_signals_flow_into_next_cycle_corpus(self, temp_workspace: Path) -> None:
        """The injected keys must be consumable by the signals phase verbatim."""
        from evolver.gep.asset_store import consume_pending_signals

        record_feedback(EvaluationFeedback(primary_score=0.1, success=False))
        pending = consume_pending_signals()
        assert FEEDBACK_SIGNAL_DEGRADED in pending
        # consumed → cleared for the next reader
        assert consume_pending_signals() == []

    def test_load_recent_respects_limit_and_bad_lines(self, temp_workspace: Path) -> None:
        path = feedback_journal_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "not-json\n"
            + "\n".join(
                EvaluationFeedback(primary_score=i / 10).model_dump_json() for i in range(5)
            )
            + "\n",
            encoding="utf-8",
        )
        rows = load_recent_feedback(limit=3)
        assert len(rows) == 3
        assert rows[-1]["primary_score"] == 0.4
