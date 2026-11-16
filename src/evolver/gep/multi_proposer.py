"""Mechanism-diverse multi-proposer.

Methodology inspired by Self-Harness (arXiv:2606.09498,
``proposer/src/self_harness_proposer/multi_proposer.py``). No Node.js
equivalent; evolver.py self-research addition (Sprint C2).

Generates N *mechanism-diverse* proposals in one round. Diversity is enforced
structurally: proposals are generated slot-by-slot (or parsed from a single
multi-slot response), already-generated proposals are fed back into the
prompt, and a ``(cluster, mechanism_family, target_hook)`` signature is
deduplicated — a duplicate triggers a retry (≤2), then degrades to a
first-class ``decline``.

``strict_noop`` makes decline a first-class outcome: when no safe, reusable
change follows from the evidence, the proposer may decline a slot instead of
inventing a change.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LlmCall = Callable[[str], str]

Decision = Literal["propose", "decline"]

_MAX_DUP_RETRIES = 2


class Proposal(BaseModel):
    """One mechanism-diverse proposal slot outcome."""

    model_config = ConfigDict(extra="forbid")
    slot_index: int
    decision: Decision = "propose"
    cluster_id: str | None = None
    mechanism_family: str = ""
    target_hook: str | None = None
    rationale: str = ""
    decline_reason: str | None = None

    @field_validator("mechanism_family")
    @classmethod
    def _family_nonempty(cls, v: str) -> str:
        if v and not v.strip():
            raise ValueError("mechanism_family must not be blank")
        return v.strip()

    @field_validator("rationale", "decline_reason")
    @classmethod
    def _text_trim(cls, v: str | None) -> str | None:
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v


class MultiProposerRequest(BaseModel):
    """Inputs for one multi-proposal round."""

    model_config = ConfigDict(extra="forbid")
    diagnosis_brief: str = ""
    causal_clusters_brief: str = ""
    route_count: int = 4
    strict_noop: bool = True
    extra_context: str = ""
    already_generated: list[Proposal] = Field(default_factory=list)


def proposal_signature(proposal: Proposal) -> tuple[str, str, str] | None:
    """Dedup key ``(cluster_id, mechanism_family, target_hook)``.

    ``None`` for declines (declines never collide with proposals).
    """
    if proposal.decision != "propose":
        return None
    return (
        proposal.cluster_id or "",
        proposal.mechanism_family,
        proposal.target_hook or "",
    )


def build_multi_proposer_prompt(request: MultiProposerRequest) -> str:
    """Render the strict-JSON multi-slot prompt for the LLM.

    Demands exactly ``route_count`` proposal objects (one per slot), with
    *distinct* ``(cluster, mechanism_family, target_hook)`` signatures and
    first-class ``decline`` support under ``strict_noop``.
    """
    lines: list[str] = [
        "You are a mechanism-diverse evolution proposer. Propose bounded, "
        "safe harness changes for the current evolution state.",
        "",
        "CONTEXT:",
        f"- diagnosis_brief: {request.diagnosis_brief or '(none)'}",
        f"- causal_clusters_brief: {request.causal_clusters_brief or '(none)'}",
        f"- strict_noop: {request.strict_noop}",
    ]
    if request.extra_context:
        lines.extend(["", "EXTRA CONTEXT:", request.extra_context])
    lines.extend(
        [
            "",
            "ALREADY GENERATED PROPOSALS (do NOT repeat their mechanism):",
        ]
    )
    if request.already_generated:
        for p in request.already_generated:
            lines.append(
                f"- slot {p.slot_index}: {p.decision} "
                f"family={p.mechanism_family or '-'} "
                f"hook={p.target_hook or '-'} "
                f"cluster={p.cluster_id or '-'}"
            )
    else:
        lines.append("- (none)")
    lines.extend(
        [
            "",
            "RULES:",
            "- Emit EXACTLY one proposal per slot, slots 0.."
            f"{request.route_count - 1}, no more, no fewer.",
            "- Each proposal must target a DIFFERENT mechanism_family "
            "(mechanism diversity) or a different cluster.",
            "- Select ONE high-confidence terminal-cause cluster; do not "
            "treat a large bucket as actionable by itself.",
            "- If no safe, reusable change follows from the evidence, "
            f"emit decision=decline with a reason "
            f"(strict_noop={request.strict_noop}).",
            "",
            "Respond with ONLY a JSON object of this shape:",
            '{"proposals": [',
            '  {"slot_index": 0, "decision": "propose", "cluster_id": "<id or null>", '
            '"mechanism_family": "<family>", "target_hook": "<hook or null>", '
            '"rationale": "<why this mechanism>"}',
            '  {"slot_index": 1, "decision": "decline", "decline_reason": "<why>"}',
            "]}",
        ]
    )
    return "\n".join(lines)


def _extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from *text* (fenced or bare)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("response contains no JSON object") from None
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("response JSON is not an object")
    return parsed


def parse_multi_proposal_response(
    text: str,
    *,
    route_count: int,
) -> list[Proposal]:
    """Strictly parse the multi-slot response into :class:`Proposal` list.

    Raises :class:`ValueError` on malformed JSON, wrong slot coverage (missing
    or duplicate ``slot_index``), or invalid fields.
    """
    payload = _extract_json_object(text)
    raw_proposals = payload.get("proposals")
    if not isinstance(raw_proposals, list):
        raise ValueError("response missing 'proposals' list")

    by_slot: dict[int, dict[str, Any]] = {}
    for raw in raw_proposals:
        if not isinstance(raw, dict):
            raise ValueError("proposal entry is not an object")
        slot = raw.get("slot_index")
        if not isinstance(slot, int):
            raise ValueError(f"proposal missing integer slot_index: {raw!r}")
        if slot in by_slot:
            raise ValueError(f"duplicate slot_index: {slot}")
        by_slot[slot] = raw

    expected = set(range(route_count))
    if set(by_slot) != expected:
        missing = expected - set(by_slot)
        extra = set(by_slot) - expected
        raise ValueError(f"slot coverage mismatch missing={sorted(missing)} extra={sorted(extra)}")

    proposals: list[Proposal] = []
    for slot in range(route_count):
        raw = by_slot[slot]
        decision = raw.get("decision", "propose")
        if decision not in ("propose", "decline"):
            raise ValueError(f"slot {slot} invalid decision: {decision!r}")
        if decision == "decline":
            decline_reason = raw.get("decline_reason")
            if not isinstance(decline_reason, str) or not decline_reason.strip():
                raise ValueError(f"slot {slot} decline missing decline_reason")
            proposals.append(
                Proposal(
                    slot_index=slot,
                    decision="decline",
                    decline_reason=decline_reason.strip(),
                )
            )
            continue
        family = raw.get("mechanism_family")
        if not isinstance(family, str) or not family.strip():
            raise ValueError(f"slot {slot} propose missing mechanism_family")
        rationale = raw.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError(f"slot {slot} propose missing rationale")
        cluster_id = raw.get("cluster_id")
        target_hook = raw.get("target_hook")
        proposals.append(
            Proposal(
                slot_index=slot,
                decision="propose",
                cluster_id=(
                    str(cluster_id) if isinstance(cluster_id, str) and cluster_id else None
                ),
                mechanism_family=family.strip(),
                target_hook=(
                    str(target_hook) if isinstance(target_hook, str) and target_hook else None
                ),
                rationale=rationale.strip(),
            )
        )
    return proposals


def _degrade_to_decline(proposal: Proposal, reason: str) -> Proposal:
    return Proposal(
        slot_index=proposal.slot_index,
        decision="decline",
        decline_reason=reason,
    )


def build_slot_repair_prompt(
    request: MultiProposerRequest,
    existing_proposals: Sequence[Proposal] | list[Proposal],
    duplicate_slot: int,
    violations: Sequence[str],
) -> str:
    """Ask ONLY for the offending slot/fields rather than regenerating all slots (S-7)."""
    slate_view = json.dumps(
        [p.model_dump() for p in existing_proposals],
        indent=1,
        ensure_ascii=False,
    )
    bullets = "\n".join(f"- {v}" for v in violations)
    return "\n".join(
        [
            f"# Repair proposal slot {duplicate_slot} (reply with ONLY a compact JSON patch)",
            "",
            "Previous slot check found violations:",
            bullets,
            "",
            "Do NOT re-send valid slots. Return either a full slate or a delta patch like:",
            '{"replace_slots": {"'
            + str(duplicate_slot)
            + '": {"slot_index": '
            + str(duplicate_slot)
            + ', "decision": "propose", "cluster_id": null, '
            + '"mechanism_family": "<new_family>", "target_hook": "<hook>", '
            + '"rationale": "<why>"}}}',
            "",
            f"CONTEXT: diagnosis_brief={request.diagnosis_brief or '(none)'}",
            "EXISTING PROPOSALS:",
            slate_view,
        ]
    )


def merge_proposal_patch(
    existing_proposals: list[Proposal],
    text: str,
    *,
    route_count: int,
    target_slot: int | None = None,
) -> list[Proposal]:
    """Parse either a delta repair patch or a full multi-proposal response."""
    payload = _extract_json_object(text)
    if "proposals" in payload:
        return parse_multi_proposal_response(text, route_count=route_count)

    replace_slots = payload.get("replace_slots")
    set_fields = payload.get("set_fields")
    if not isinstance(replace_slots, dict) and not isinstance(set_fields, dict):
        raise ValueError("repair JSON has neither `proposals` nor `replace_slots`/`set_fields`")

    by_slot: dict[int, Proposal] = {p.slot_index: p for p in existing_proposals}
    if isinstance(replace_slots, dict):
        for raw_idx, raw_obj in replace_slots.items():
            idx = int(raw_idx)
            if isinstance(raw_obj, dict):
                obj = dict(raw_obj)
                obj.setdefault("slot_index", idx)
                by_slot[idx] = Proposal.model_validate(obj)
    if isinstance(set_fields, dict):
        for raw_idx, fields in set_fields.items():
            idx = int(raw_idx)
            if idx in by_slot and isinstance(fields, dict):
                merged_data = {**by_slot[idx].model_dump(), **fields, "slot_index": idx}
                by_slot[idx] = Proposal.model_validate(merged_data)

    if target_slot is not None and target_slot not in by_slot:
        raise ValueError(f"repair patch did not provide slot {target_slot}")
    return [by_slot[i] for i in sorted(by_slot)]


def generate_multi_proposals(
    request: MultiProposerRequest,
    llm_call: LlmCall,
) -> list[Proposal]:
    """Generate *route_count* mechanism-diverse proposals (slot-by-slot).

    Each slot receives the prompt with already-generated proposals fed back;
    a duplicate ``(cluster, family, hook)`` signature triggers a targeted delta
    repair retry (<=2), then degrades to a ``decline``.
    """
    proposals: list[Proposal] = []
    seen_signatures: set[tuple[str, str, str]] = set()
    for slot in range(request.route_count):
        slot_request = request.model_copy(
            update={"already_generated": list(proposals), "route_count": request.route_count}
        )
        raw = llm_call(build_multi_proposer_prompt(slot_request))
        parsed = parse_multi_proposal_response(raw, route_count=request.route_count)
        if len(parsed) != request.route_count or parsed[slot].slot_index != slot:
            raise ValueError(f"slot {slot}: response did not cover all slots in order")
        proposal = parsed[slot]
        signature = proposal_signature(proposal)
        if signature is not None:
            if signature in seen_signatures:
                degraded: Proposal | None = None
                for _attempt in range(_MAX_DUP_RETRIES):
                    repair_prompt = build_slot_repair_prompt(
                        slot_request,
                        proposals,
                        slot,
                        [f"duplicate mechanism signature {signature}"],
                    )
                    retry_raw = llm_call(repair_prompt)
                    retry_parsed = merge_proposal_patch(
                        proposals,
                        retry_raw,
                        route_count=request.route_count,
                        target_slot=slot,
                    )
                    retry_proposal = next(
                        (p for p in retry_parsed if p.slot_index == slot), retry_parsed[-1]
                    )
                    if (
                        proposal_signature(retry_proposal) is not None
                        and proposal_signature(retry_proposal) not in seen_signatures
                    ):
                        degraded = retry_proposal
                        break
                proposal = degraded or _degrade_to_decline(
                    proposal, "duplicate mechanism signature after retries"
                )
            if proposal_signature(proposal) is not None:
                seen_signatures.add(proposal_signature(proposal) or ("", "", ""))
        proposals.append(proposal)
    return proposals


__all__ = [
    "LlmCall",
    "MultiProposerRequest",
    "Proposal",
    "build_multi_proposer_prompt",
    "build_slot_repair_prompt",
    "generate_multi_proposals",
    "merge_proposal_patch",
    "parse_multi_proposal_response",
    "proposal_signature",
]
