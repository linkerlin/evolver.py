"""Tests for evolver.gep.diagnosis.clusters (Sprint B2)."""

from __future__ import annotations

from evolver.gep.diagnosis.clusters import (
    CausalCluster,
    CausalSignature,
    build_causal_clusters,
    cluster_guidance,
    render_cluster_brief,
    signature_of,
)
from evolver.gep.diagnosis.schemas import (
    CausalAnalysis,
    StageRecord,
)


def _analysis(
    eid: str,
    *,
    terminal_cause: str | None = None,
    criticality: str = "root_cause",
    mechanism: str = "no_progress",
) -> CausalAnalysis:
    """Build an analysis; *terminal_cause* None → unattributed (degraded)."""
    stages: list[StageRecord] = []
    if terminal_cause is not None:
        stages.append(
            StageRecord(
                stage_index=0,
                terminal_cause=terminal_cause,
                criticality=criticality,  # type: ignore[arg-type]
                agent_mechanism=mechanism,
            )
        )
    return CausalAnalysis(
        event_id=eid,
        terminal_failure_kind="unknown",
        stages=stages,
        root_cause_stage=0 if terminal_cause is not None else None,
    )


class TestSignatureOf:
    def test_attributed(self) -> None:
        a = _analysis("e1", terminal_cause="agent_timeout")
        sig = signature_of(a)
        assert sig is not None
        assert sig.terminal_cause == "agent_timeout"
        assert sig.criticality == "root_cause"
        assert sig.agent_mechanism == "no_progress"

    def test_unattributed_returns_none(self) -> None:
        a = _analysis("e1")  # no root cause
        assert signature_of(a) is None


class TestBuildCausalClusters:
    def test_groups_same_signature(self) -> None:
        analyses = [
            _analysis("e1", terminal_cause="agent_timeout"),
            _analysis("e2", terminal_cause="agent_timeout"),
            _analysis("e3", terminal_cause="missing_dependency"),
        ]
        clusters = build_causal_clusters(analyses)
        assert len(clusters) == 2
        by_cause = {c.signature.terminal_cause: c for c in clusters}
        assert by_cause["agent_timeout"].size == 2
        assert set(by_cause["agent_timeout"].case_ids) == {"e1", "e2"}
        assert by_cause["missing_dependency"].size == 1

    def test_sorts_root_cause_first_then_size(self) -> None:
        analyses = [
            _analysis("e1", terminal_cause="a", criticality="recovered_friction"),
            _analysis("e2", terminal_cause="b", criticality="root_cause"),
            _analysis("e3", terminal_cause="c", criticality="root_cause"),
            _analysis("e4", terminal_cause="c", criticality="root_cause"),
        ]
        clusters = build_causal_clusters(analyses)
        # root_cause clusters first; among them, size desc (c(2) before b(1))
        assert [c.signature.criticality for c in clusters][:2] == [
            "root_cause",
            "root_cause",
        ]
        assert clusters[0].signature.terminal_cause == "c"
        assert clusters[0].size == 2
        assert clusters[-1].signature.criticality == "recovered_friction"

    def test_unattributed_skipped(self) -> None:
        analyses = [
            _analysis("e1", terminal_cause="x"),
            _analysis("e2"),  # unattributed → skipped
        ]
        clusters = build_causal_clusters(analyses)
        assert len(clusters) == 1
        assert clusters[0].case_ids == ["e1"]

    def test_empty_returns_empty(self) -> None:
        assert build_causal_clusters([]) == []

    def test_distinct_signatures_kept_separate(self) -> None:
        # same terminal_cause but different mechanism → different cluster
        analyses = [
            _analysis("e1", terminal_cause="x", mechanism="m1"),
            _analysis("e2", terminal_cause="x", mechanism="m2"),
        ]
        clusters = build_causal_clusters(analyses)
        assert len(clusters) == 2


class TestClusterGuidance:
    def test_per_criticality(self) -> None:
        assert "high-confidence" in cluster_guidance(
            CausalSignature(
                terminal_cause="x",
                criticality="root_cause",
                agent_mechanism="m",
            )
        )
        assert "NOT actionable" in cluster_guidance(
            CausalSignature(
                terminal_cause="x",
                criticality="recovered_friction",
                agent_mechanism="m",
            )
        )


class TestRenderClusterBrief:
    def test_empty_returns_empty(self) -> None:
        assert render_cluster_brief([]) == ""

    def test_renders_header_and_cluster(self) -> None:
        clusters = build_causal_clusters([_analysis("e1", terminal_cause="agent_timeout")])
        brief = render_cluster_brief(clusters)
        assert "Causal Failure Clusters" in brief
        assert "Passing cases are regression tests" in brief
        assert "agent_timeout" in brief
        assert "e1" in brief
        assert "high-confidence" in brief

    def test_model_dump_round_trip(self) -> None:
        clusters = build_causal_clusters([_analysis("e1", terminal_cause="agent_timeout")])
        rebuilt = CausalCluster.model_validate(clusters[0].model_dump())
        assert rebuilt.size == 1
        assert rebuilt.signature.terminal_cause == "agent_timeout"
