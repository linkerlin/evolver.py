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


class TestRollingWindow:
    """Round-24: soak metrics cover the most recent GATE_SOAK_MIN_RUNS gated
    events. An all-time window meant a pre-calibration flake never expired —
    the only dilution path was deliberately feeding bad mutations."""

    @staticmethod
    def _gated(i: int) -> dict[str, object]:
        return {
            "timestamp": f"2026-09-{i + 1:02d}T00:00:00Z",
            "acceptance_result": {"reason": "t0_only_no_regression"},
        }

    @staticmethod
    def _flaky_rejection(i: int) -> dict[str, object]:
        # shadow rejection with a green cascade = the false-kill signature
        return {
            "timestamp": f"2026-09-{i + 1:02d}T00:00:00Z",
            "acceptance_result": {"shadow": True, "would_accept": False},
            "validation_report": {"overall_ok": True},
        }

    def test_pre_calibration_flake_ages_out(self) -> None:
        events = [self._flaky_rejection(1)] + [self._gated(i) for i in range(24)]
        m = summarize_acceptance(events)  # default window = GATE_SOAK_MIN_RUNS
        assert m["window_runs"] == 20
        assert m["gated_runs"] == 20
        assert m["shadow_rejected"] == 0
        assert m["false_kill_risk"] is None

    def test_recent_flake_still_counts(self) -> None:
        events = [self._gated(i) for i in range(24)] + [self._flaky_rejection(24)]
        m = summarize_acceptance(events)
        assert m["shadow_rejected"] == 1
        assert m["validation_disagreements"] == 1
        assert m["false_kill_risk"] == 1.0

    def test_fewer_events_than_window_includes_all(self) -> None:
        events = [self._flaky_rejection(1)] + [self._gated(i) for i in range(3)]
        m = summarize_acceptance(events)
        assert m["window_runs"] == 4
        assert m["shadow_rejected"] == 1

    def test_explicit_window_overrides(self) -> None:
        events = [self._gated(i) for i in range(5)] + [self._flaky_rejection(5)]
        m = summarize_acceptance(events, window_runs=2)
        assert m["window_runs"] == 2
        assert m["shadow_rejected"] == 1  # the flake IS within the last 2
