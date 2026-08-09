"""Tests for evolver.gep.multi_proposer (Sprint C2)."""

from __future__ import annotations

import json

import pytest

from evolver.gep.multi_proposer import (
    MultiProposerRequest,
    Proposal,
    build_multi_proposer_prompt,
    generate_multi_proposals,
    parse_multi_proposal_response,
    proposal_signature,
)


def _propose(slot: int, family: str, cluster: str | None = "c1", hook: str | None = None) -> dict:
    p: dict = {
        "slot_index": slot,
        "decision": "propose",
        "cluster_id": cluster,
        "mechanism_family": family,
        "target_hook": hook,
        "rationale": f"fix {family}",
    }
    return p


def _decline(slot: int, reason: str = "no safe change") -> dict:
    return {"slot_index": slot, "decision": "decline", "decline_reason": reason}


def _resp(*proposals: dict) -> str:
    return json.dumps({"proposals": list(proposals)})


class TestProposalSchema:
    def test_minimal_propose(self) -> None:
        p = Proposal(slot_index=0, mechanism_family="prompt_instruction")
        assert p.decision == "propose"

    def test_extra_forbidden(self) -> None:
        with pytest.raises(Exception):
            Proposal(slot_index=0, mechanism_family="x", bogus=True)  # type: ignore[call-arg]

    def test_blank_family_rejected(self) -> None:
        with pytest.raises(Exception):
            Proposal(slot_index=0, mechanism_family="   ")


class TestProposalSignature:
    def test_propose_signature(self) -> None:
        p = Proposal(
            slot_index=0,
            cluster_id="c1",
            mechanism_family="prompt_instruction",
            target_hook="sys",
        )
        assert proposal_signature(p) == ("c1", "prompt_instruction", "sys")

    def test_decline_has_no_signature(self) -> None:
        p = Proposal(slot_index=0, decision="decline", decline_reason="no")
        assert proposal_signature(p) is None


class TestBuildPrompt:
    def test_contains_contract_and_feedback(self) -> None:
        request = MultiProposerRequest(
            diagnosis_brief="brief",
            route_count=2,
            already_generated=[
                Proposal(slot_index=0, mechanism_family="prompt_instruction")
            ],
        )
        prompt = build_multi_proposer_prompt(request)
        assert "ALREADY GENERATED PROPOSALS" in prompt
        assert "prompt_instruction" in prompt
        assert "proposals" in prompt
        assert "decline" in prompt


class TestParseResponse:
    def test_valid_mixed(self) -> None:
        proposals = parse_multi_proposal_response(
            _resp(_propose(0, "prompt_instruction"), _decline(1)),
            route_count=2,
        )
        assert len(proposals) == 2
        assert proposals[0].mechanism_family == "prompt_instruction"
        assert proposals[1].decision == "decline"
        assert proposals[1].decline_reason == "no safe change"

    def test_fenced_json(self) -> None:
        raw = "```json\n" + _resp(_propose(0, "x")) + "\n```"
        proposals = parse_multi_proposal_response(raw, route_count=1)
        assert proposals[0].mechanism_family == "x"

    def test_missing_slots_raises(self) -> None:
        with pytest.raises(ValueError, match="slot coverage mismatch"):
            parse_multi_proposal_response(_resp(_propose(0, "x")), route_count=2)

    def test_duplicate_slot_raises(self) -> None:
        with pytest.raises(ValueError, match="duplicate slot_index"):
            parse_multi_proposal_response(
                _resp(_propose(0, "x"), _propose(0, "y")), route_count=2
            )

    def test_decline_without_reason_raises(self) -> None:
        with pytest.raises(ValueError, match="decline missing decline_reason"):
            parse_multi_proposal_response(
                _resp({"slot_index": 0, "decision": "decline"}), route_count=1
            )

    def test_propose_without_family_raises(self) -> None:
        with pytest.raises(ValueError, match="missing mechanism_family"):
            parse_multi_proposal_response(
                _resp({"slot_index": 0, "decision": "propose"}), route_count=1
            )

    def test_no_json_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_multi_proposal_response("no json", route_count=1)


class TestGenerate:
    def test_generates_all_slots(self) -> None:
        request = MultiProposerRequest(route_count=3)
        responses = iter(
            [
                _resp(_propose(0, "a"), _propose(1, "b"), _propose(2, "c")),
                _resp(_propose(0, "a"), _propose(1, "b"), _propose(2, "c")),
                _resp(_propose(0, "a"), _propose(1, "b"), _propose(2, "c")),
            ]
        )
        proposals = generate_multi_proposals(request, lambda _p: next(responses))
        assert len(proposals) == 3
        assert {p.mechanism_family for p in proposals} == {"a", "b", "c"}

    def test_duplicate_degrades_to_decline(self) -> None:
        # slot 1 repeats slot 0's family; retries also repeat → decline
        request = MultiProposerRequest(route_count=2)
        responses = iter(
            [
                _resp(_propose(0, "same"), _propose(1, "same")),  # slot 0
                _resp(_propose(0, "same"), _propose(1, "same")),  # slot 1 initial
                _resp(_propose(0, "same"), _propose(1, "same")),  # retry 1
                _resp(_propose(0, "same"), _propose(1, "same")),  # retry 2
            ]
        )
        proposals = generate_multi_proposals(request, lambda _p: next(responses))
        assert proposals[0].decision == "propose"
        assert proposals[1].decision == "decline"
        assert "duplicate" in (proposals[1].decline_reason or "")

    def test_retry_accepts_distinct_mechanism(self) -> None:
        # slot 1 duplicates first, then retry returns a distinct family
        request = MultiProposerRequest(route_count=2)
        responses = iter(
            [
                _resp(_propose(0, "same"), _propose(1, "same")),
                _resp(_propose(0, "same"), _propose(1, "other")),
            ]
        )
        proposals = generate_multi_proposals(request, lambda _p: next(responses))
        assert proposals[1].decision == "propose"
        assert proposals[1].mechanism_family == "other"

    def test_decline_allowed_by_default(self) -> None:
        request = MultiProposerRequest(route_count=1, strict_noop=True)
        proposals = generate_multi_proposals(
            request, lambda _p: _resp(_decline(0))
        )
        assert proposals[0].decision == "decline"
