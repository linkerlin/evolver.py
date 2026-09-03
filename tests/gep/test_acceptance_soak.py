"""Acceptance-gate soak promotion verdicts (v1.107.0).

gate_soak_recommendation maps shadow metrics onto a readiness verdict
(collecting / ready / over- / under-intercepting / false_kill_high); the
actual enforcement switch stays a human decision.
"""

from __future__ import annotations

import pytest

from evolver.gep.acceptance.report import gate_soak_recommendation, summarize_acceptance


def _metrics(gated: int, rejected: int, disagreements: int = 0) -> dict:
    return {
        "gated_runs": gated,
        "shadow_rejected": rejected,
        "interception_rate": round(rejected / gated, 4) if gated else 0.0,
        "validation_disagreements": disagreements,
        "false_kill_risk": round(disagreements / rejected, 4) if rejected else None,
        "window": {"first": None, "last": None},
    }


class TestVerdicts:
    def test_insufficient_samples_collecting(self) -> None:
        verdict = gate_soak_recommendation(_metrics(gated=5, rejected=1))
        assert verdict["verdict"] == "collecting"
        assert "20" in verdict["reasons"][0]

    def test_ready_band(self) -> None:
        verdict = gate_soak_recommendation(_metrics(gated=100, rejected=15))
        assert verdict["verdict"] == "ready"
        assert verdict["enforce_hint"].startswith("EVOLVER_ACCEPTANCE_SHADOW=0")

    def test_false_kill_high_beats_everything(self) -> None:
        verdict = gate_soak_recommendation(_metrics(gated=50, rejected=10, disagreements=5))
        assert verdict["verdict"] == "false_kill_high"

    def test_over_intercepting(self) -> None:
        verdict = gate_soak_recommendation(_metrics(gated=40, rejected=30))
        assert verdict["verdict"] == "over_intercepting"

    def test_under_intercepting_with_zero_rejections(self) -> None:
        verdict = gate_soak_recommendation(_metrics(gated=40, rejected=0))
        assert verdict["verdict"] == "under_intercepting"
        assert verdict["reasons"][0].startswith("interception_rate=0.0")

    def test_criteria_snapshot_included(self) -> None:
        verdict = gate_soak_recommendation(_metrics(gated=0, rejected=0))
        assert verdict["criteria"]["min_runs"] == 20
        assert verdict["criteria"]["interception_band"] == [0.05, 0.5]
        assert verdict["criteria"]["max_false_kill"] == 0.1

    def test_thresholds_env_tunable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("evolver.config.GATE_SOAK_MIN_RUNS", 3)
        verdict = gate_soak_recommendation(_metrics(gated=3, rejected=1))
        # 1/3 ≈ 0.333 in [0.05, 0.5], false_kill None → ready.
        assert verdict["verdict"] == "ready"


class TestWindow:
    def test_window_from_events(self) -> None:
        events = [
            {"timestamp": "2026-09-04T03:00:00Z", "acceptance_result": {"shadow": True}},
            {"timestamp": "2026-09-04T01:00:00Z", "acceptance_result": {"shadow": True}},
            {"timestamp": "ignored", "no_gate": True},
        ]
        metrics = summarize_acceptance(events)
        assert metrics["gated_runs"] == 2
        assert metrics["window"]["first"] == "2026-09-04T01:00:00Z"
        assert metrics["window"]["last"] == "2026-09-04T03:00:00Z"
