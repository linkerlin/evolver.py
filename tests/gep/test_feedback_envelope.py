"""Feedback envelope contracts (v1.94.0 parity).

Behavioral port of Node ``test/feedbackEnvelope.test.js`` (module is obfuscated
at HEAD; the plaintext tests are the contract).
"""

from __future__ import annotations

import json

from evolver.gep.feedback_envelope import (
    aggregate_feedback_envelopes,
    evidence_ref,
    from_outcome_scalar,
    from_scalar_feedback,
    with_conflict,
)


def evidence(ref_id: str = "event-1") -> dict:
    return evidence_ref("evolution_outcome", ref_id)


class TestFeedbackEnvelope:
    def test_adapts_scalar_feedback_into_typed_metadata(self) -> None:
        envelope = from_scalar_feedback(
            {
                "priority_axis": "user_preference",
                "scalar": 0.9,
                "evaluator_attention": {"level": "full"},
                "evidence_ref": evidence(),
            }
        )
        assert envelope["priority_axis"] == "user_preference"
        assert envelope["label"] == "positive"
        assert envelope["scalar"] == 0.9
        assert envelope["indecision"] is False
        assert envelope["conflict"] is False
        assert envelope["evaluator_attention"]["level"] == "full"
        assert envelope["evidence_ref"]["kind"] == "evolution_outcome"

    def test_midpoint_scalar_is_indecision(self) -> None:
        envelope = from_scalar_feedback(
            {
                "priority_axis": "task_success",
                "scalar": 0.5,
                "evidence_ref": evidence_ref("external", "judge-1"),
            }
        )
        assert envelope["label"] == "mixed"
        assert envelope["indecision"] is True
        assert envelope["uncertainty"] > 0.5

    def test_uses_existing_effective_scalar_without_replacing_outcome(self) -> None:
        outcome = {"status": "failed", "score": 0.2, "user_override": 0.8}
        envelope = from_outcome_scalar(
            outcome, {"priority_axis": "user_preference", "evidence_ref": evidence()}
        )
        assert outcome["score"] == 0.2
        assert outcome["user_override"] == 0.8
        assert envelope["scalar"] == 0.8
        assert envelope["label"] == "positive"

    def test_round_trips_as_snake_case_json(self) -> None:
        envelope = with_conflict(
            from_scalar_feedback(
                {
                    "priority_axis": "safety",
                    "scalar": 0.1,
                    "evaluator_attention": {"level": "limited"},
                    "evidence_ref": evidence_ref("review", "review-1", {"summary": "unsafe patch"}),
                }
            )
        )
        encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        assert '"priority_axis":"safety"' in encoded
        assert '"evaluator_attention":' in encoded
        assert '"kind":"review"' in encoded
        assert json.loads(encoded) == envelope

    def test_conflict_raises_aggregate_uncertainty_instead_of_winner(self) -> None:
        positive = from_scalar_feedback(
            {
                "priority_axis": "quality",
                "scalar": 0.9,
                "evaluator_attention": {"level": "full"},
                "evidence_ref": evidence("positive"),
            }
        )
        negative = with_conflict(
            from_scalar_feedback(
                {
                    "priority_axis": "quality",
                    "scalar": 0.1,
                    "evaluator_attention": {"level": "full"},
                    "evidence_ref": evidence("negative"),
                }
            )
        )
        single = aggregate_feedback_envelopes([positive])
        conflicted = aggregate_feedback_envelopes([positive, negative])
        assert single["dominant_label"] == "positive"
        assert conflicted["dominant_label"] is None
        assert conflicted["uncertainty"] > single["uncertainty"]

    def test_low_attention_raises_uncertainty_without_changing_label(self) -> None:
        full = from_scalar_feedback(
            {
                "priority_axis": "task_success",
                "scalar": 0.85,
                "evaluator_attention": {"level": "full"},
                "evidence_ref": evidence("full"),
            }
        )
        skimmed = from_scalar_feedback(
            {
                "priority_axis": "task_success",
                "scalar": 0.85,
                "evaluator_attention": {"level": "skimmed"},
                "evidence_ref": evidence("skimmed"),
            }
        )
        assert full["label"] == "positive"
        assert skimmed["label"] == "positive"
        assert skimmed["uncertainty"] > full["uncertainty"]

        full_agg = aggregate_feedback_envelopes([full])
        skimmed_agg = aggregate_feedback_envelopes([skimmed])
        assert full_agg["dominant_label"] == "positive"
        assert skimmed_agg["dominant_label"] is None
        assert skimmed_agg["uncertainty"] > full_agg["uncertainty"]

    def test_maximally_uncertain_with_no_labels(self) -> None:
        aggregate = aggregate_feedback_envelopes([])
        assert aggregate["dominant_label"] is None
        assert aggregate["sample_count"] == 0
        assert aggregate["uncertainty"] == 1
