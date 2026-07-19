"""Capability candidates tests (Sprint 15.5) — ports candidates.test.js + probes."""

from __future__ import annotations

from evolver.gep.candidates import (
    expand_signals,
    extract_capability_candidates,
    render_candidates_preview,
)
from evolver.gep.hash_utils import stable_hash


class TestExpandSignals:
    def test_derives_structured_learning_tags(self) -> None:
        tags = expand_signals(["perf_bottleneck", "stable_success_plateau"], "")
        assert "problem:performance" in tags
        assert "problem:stagnation" in tags
        assert "action:optimize" in tags
        assert "action:innovate" in tags

    def test_reliability_and_protocol(self) -> None:
        assert "problem:reliability" in expand_signals(["error_spike"], "")
        assert "action:repair" in expand_signals(["log_error"], "")
        proto = expand_signals(["protocol_drift"], "")
        assert "problem:protocol" in proto
        assert "area:prompt" in proto

    def test_colon_prefix_kept(self) -> None:
        tags = expand_signals(["foo:bar"], "")
        assert "foo:bar" in tags
        assert "foo" in tags

    def test_validation_risk(self) -> None:
        tags = expand_signals(["x"], "validation failed")
        assert "risk:validation" in tags
        assert "problem:reliability" in tags

    def test_text_only_performance(self) -> None:
        tags = expand_signals([], "performance bottleneck latency")
        assert "problem:performance" in tags
        assert "action:optimize" in tags


class TestExtractCapabilityCandidates:
    def test_failure_driven_from_repeated_failed_capsules(self) -> None:
        result = extract_capability_candidates(
            {
                "recentSessionTranscript": "",
                "signals": ["perf_bottleneck"],
                "recentFailedCapsules": [
                    {
                        "trigger": ["perf_bottleneck"],
                        "failure_reason": "validation failed because latency stayed high",
                        "outcome": {"status": "failed"},
                    },
                    {
                        "trigger": ["perf_bottleneck"],
                        "failure_reason": "constraint violation after slow path regression",
                        "outcome": {"status": "failed"},
                    },
                ],
            }
        )
        failure = next((c for c in result if c["source"] == "failed_capsules"), None)
        assert failure is not None
        assert "problem:performance" in failure["tags"]
        assert failure["title"] == "Resolve recurring performance regressions"
        assert failure["id"] == f"cand_{stable_hash('failed:problem:performance')}"

    def test_signal_whitelist_perf(self) -> None:
        result = extract_capability_candidates(
            {"signals": ["perf_bottleneck"], "recentFailedCapsules": []}
        )
        assert len(result) == 1
        cand = result[0]
        assert cand["source"] == "signals"
        assert cand["title"] == "Resolve performance bottleneck"
        assert cand["id"] == f"cand_{stable_hash('perf_bottleneck')}"
        assert cand["tags"] == expand_signals(["perf_bottleneck"], "")

    def test_unknown_signal_no_candidate(self) -> None:
        result = extract_capability_candidates(
            {"signals": ["unknown_xyz"], "recentFailedCapsules": []}
        )
        assert result == []

    def test_needs_two_failed_capsules(self) -> None:
        result = extract_capability_candidates(
            {
                "signals": [],
                "recentFailedCapsules": [
                    {
                        "trigger": ["auth_error"],
                        "failure_reason": "token expired",
                        "outcome": {"status": "failed"},
                    }
                ],
            }
        )
        assert result == []

    def test_reliability_failed_group(self) -> None:
        result = extract_capability_candidates(
            {
                "signals": [],
                "recentFailedCapsules": [
                    {
                        "trigger": ["auth_error"],
                        "failure_reason": "token expired",
                        "outcome": {"status": "failed"},
                    },
                    {
                        "trigger": ["auth_error"],
                        "failure_reason": "token invalid",
                        "outcome": {"status": "failed"},
                    },
                ],
            }
        )
        assert len(result) == 1
        assert result[0]["title"] == "Repair recurring reliability failures"
        assert result[0]["id"] == f"cand_{stable_hash('failed:problem:reliability')}"

    def test_skips_successful_outcomes(self) -> None:
        result = extract_capability_candidates(
            {
                "signals": [],
                "recentFailedCapsules": [
                    {
                        "trigger": ["perf_bottleneck"],
                        "failure_reason": "slow",
                        "outcome": {"status": "success"},
                    },
                    {
                        "trigger": ["perf_bottleneck"],
                        "failure_reason": "slow",
                        "outcome": {"status": "failed"},
                    },
                ],
            }
        )
        assert result == []

    def test_dedupes_by_id(self) -> None:
        result = extract_capability_candidates(
            {
                "signals": ["perf_bottleneck", "perf_bottleneck"],
                "recentFailedCapsules": [],
            }
        )
        assert len(result) == 1


class TestRenderPreview:
    def test_preview_includes_shape_fields(self) -> None:
        caps = extract_capability_candidates(
            {"signals": ["perf_bottleneck"], "recentFailedCapsules": []}
        )
        text = render_candidates_preview(caps)
        assert "cand_" in text
        assert "Resolve performance bottleneck" in text
        assert "input:" in text
        assert "evidence:" in text


class TestStableHash:
    def test_fnv_matches_node(self) -> None:
        assert stable_hash("perf_bottleneck") == "7f8f52c0"
        assert stable_hash("failed:problem:performance") == "d15b81d1"
        assert stable_hash("failed:problem:reliability") == "21c55217"
