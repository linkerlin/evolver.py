"""Tests for dispatch_multi_propose_phase (Self-Harness Sprint C2)."""

from __future__ import annotations

import asyncio

import pytest

from evolver.evolve.pipeline.dispatch import dispatch_multi_propose_phase


class TestMultiProposePhase:
    def test_routes_one_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # default: ROUTES=1 → no output, ctx unchanged
        monkeypatch.delenv("EVOLVER_MULTI_PROPOSE_ROUTES", raising=False)
        ctx = {"cycle_id": "c1", "signals": []}
        result = asyncio.run(dispatch_multi_propose_phase(dict(ctx)))
        assert result == ctx

    def test_routes_gt_one_prints_contract(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EVOLVER_MULTI_PROPOSE_ROUTES", "3")
        ctx = {
            "cycle_id": "c1",
            "causal_brief": "# Causal Diagnosis",
            "causal_cluster_brief": "# Causal Failure Clusters",
            "signals": ["log_error"],
        }
        result = asyncio.run(dispatch_multi_propose_phase(dict(ctx)))
        assert result["cycle_id"] == "c1"  # ctx preserved
        # output is captured via capsys in the caller; here we assert no crash

    def test_contract_content(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        monkeypatch.setenv("EVOLVER_MULTI_PROPOSE_ROUTES", "2")
        ctx = {
            "cycle_id": "c1",
            "causal_brief": "# Causal Diagnosis",
            "causal_cluster_brief": "# Causal Failure Clusters",
        }
        asyncio.run(dispatch_multi_propose_phase(dict(ctx)))
        captured = capsys.readouterr()
        assert "BUILT_MULTI_PROPOSE_PROMPT" in captured.out
        assert "MULTI PROPOSE REQUIRED" in captured.out
        assert "proposals" in captured.out
        assert "# Causal Diagnosis" in captured.out  # diagnosis context present
        assert "# Causal Failure Clusters" in captured.out

    def test_routes_respected_in_prompt(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setenv("EVOLVER_MULTI_PROPOSE_ROUTES", "4")
        ctx = {"cycle_id": "c1"}
        asyncio.run(dispatch_multi_propose_phase(dict(ctx)))
        captured = capsys.readouterr()
        assert "slots 0..3" in captured.out  # route_count=4 → slots 0..3
