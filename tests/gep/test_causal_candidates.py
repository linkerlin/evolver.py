"""Tests for causal-cluster capability candidates (Self-Harness Sprint B2)."""

from __future__ import annotations

from evolver.gep.candidates import extract_capability_candidates
from evolver.gep.diagnosis.clusters import build_causal_clusters
from evolver.gep.diagnosis.schemas import CausalAnalysis, StageRecord


def _analysis(eid: str, *, terminal_cause: str, criticality: str = "root_cause") -> CausalAnalysis:
    return CausalAnalysis(
        event_id=eid,
        terminal_failure_kind="unknown",
        stages=[
            StageRecord(
                stage_index=0,
                terminal_cause=terminal_cause,
                criticality=criticality,  # type: ignore[arg-type]
                agent_mechanism="no_progress",
            )
        ],
        root_cause_stage=0,
    )


class TestCausalClusterCandidates:
    def test_mints_candidate_per_root_cause_cluster(self) -> None:
        analyses = [
            _analysis("e1", terminal_cause="agent_timeout"),
            _analysis("e2", terminal_cause="agent_timeout"),
            _analysis("e3", terminal_cause="missing_dependency"),
        ]
        clusters = [c.model_dump() for c in build_causal_clusters(analyses)]
        caps = extract_capability_candidates({"causal_clusters": clusters})
        # one candidate per root-cause cluster (both are root_cause)
        assert len(caps) == 2
        by_title = {c["title"]: c for c in caps}
        assert "Fix causal cluster: agent_timeout" in by_title
        cand = by_title["Fix causal cluster: agent_timeout"]
        assert cand["source"] == "causal_clusters"
        assert cand["signals"] == ["causal:root_cause:agent_timeout"]
        assert "2 case(s)" in cand["shape"]["evidence"]

    def test_skips_non_root_cause_clusters(self) -> None:
        analyses = [
            _analysis("e1", terminal_cause="x", criticality="recovered_friction"),
        ]
        clusters = [c.model_dump() for c in build_causal_clusters(analyses)]
        caps = extract_capability_candidates({"causal_clusters": clusters})
        assert caps == []

    def test_absent_clusters_unchanged(self) -> None:
        # backward compat: no causal_clusters key → same behavior as before
        caps = extract_capability_candidates({"signals": ["log_error"]})
        assert isinstance(caps, list)
        # no causal-sourced candidates
        assert all(c["source"] != "causal_clusters" for c in caps)

    def test_malformed_clusters_skipped(self) -> None:
        caps = extract_capability_candidates(
            {"causal_clusters": ["nope", {"signature": {"criticality": "root_cause"}}]}
        )
        # missing terminal_cause → skipped; non-dict → skipped
        assert caps == []

    def test_dedup_by_terminal_cause(self) -> None:
        analyses = [_analysis("e1", terminal_cause="agent_timeout")] * 2
        clusters = [c.model_dump() for c in build_causal_clusters(analyses)]
        caps = extract_capability_candidates({"causal_clusters": clusters})
        # one cluster (deduped by build) → one candidate
        assert len(caps) == 1
