"""Causal analyzer — terminal-cause-first LLM attribution.

Methodology inspired by Self-Harness (arXiv:2606.09498, ``trace.py``
``build_causal_trace_diagnosis``). No Node.js equivalent; evolver.py
self-research addition (Sprint B1).

Given a failed ``EvolutionEvent`` and an injectable ``llm_call`` callable, this
module:

1. deterministically normalizes the trace into stages
   (:mod:`evolver.gep.diagnosis.trace`),
2. classifies the terminal failure kind (deterministic hint),
3. asks the LLM to attribute ``(terminal_cause, criticality, agent_mechanism)``
   per stage under a strict JSON contract, and
4. validates the response — malformed JSON, missing fields, out-of-range
   ``criticality``, or non-snake_case signature tokens raise
   :class:`CausalAnalysisError` (never silently swallowed here).

When ``llm_call`` is ``None`` the analyzer degrades gracefully: stages keep
their deterministic spans with all-``unknown`` attribution, so the rest of the
pipeline still runs. The phase caller decides whether to persist/act on a
degraded analysis.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from evolver.gep.diagnosis.schemas import (
    CRITICALITY_RANK,
    CausalAnalysis,
    Criticality,
    StageRecord,
    TerminalFailureKind,
    is_signature_token,
)
from evolver.gep.diagnosis.trace import (
    build_stage_records,
    classify_terminal_failure,
    normalize_trace_steps,
)

#: Type of the injectable LLM call: takes a prompt, returns raw model text.
LlmCall = Callable[[str], str]


class CausalAnalysisError(Exception):
    """Raised when the LLM attribution response is malformed or invalid."""


#: Allowed terminal_failure_kind values (runtime iteration over the Literal).
_TERMINAL_KIND_VALUES: frozenset[str] = frozenset(
    {
        "missing_required_artifact",
        "missing_dependency",
        "agent_timeout",
        "verifier_runtime_error",
        "verifier_assertion",
        "reward_zero",
        "unknown",
    }
)


def build_analysis_prompt(
    stages: list[StageRecord],
    terminal_failure_kind: TerminalFailureKind,
    *,
    event_id: str = "",
) -> str:
    """Render the strict-JSON attribution prompt for the LLM.

    The contract demands one stage attribution per deterministic stage, with
    ``criticality`` in the fixed enum and snake_case signature tokens.
    """
    stage_lines = [
        f"- stage_index={s.stage_index}: {s.summary or '(no summary)'}" for s in stages
    ] or ["- (no stages)"]
    criticality_values = ", ".join(CRITICALITY_RANK)
    example = (
        '{"stage_index": 0, "terminal_cause": "<token>", '
        '"criticality": "<enum>", "agent_mechanism": "<token>", '
        '"terminal_link": null}'
    )
    lines = [
        "You are a causal-failure analyst. Attribute the terminal cause",
        "of a failed evolution event.",
        "",
        "DETERMINISTIC HINTS (do not contradict without evidence):",
        f"- event_id: {event_id or '(unknown)'}",
        f"- terminal_failure_kind: {terminal_failure_kind}",
        '- stages (a "change" step ends a stage):',
        *stage_lines,
        "",
        "RULES:",
        '- "root_cause" = the FIRST UNRECOVERABLE critical failure, NOT the',
        "  first visible (possibly recovered) tool error. Distinguish from",
        '  "recovered_friction".',
        f"- criticality MUST be one of: {criticality_values}",
        "- terminal_cause and agent_mechanism MUST be snake_case tokens",
        "  (^[a-z][a-z0-9_]*$).",
        "- Emit EXACTLY one attribution object per stage_index above.",
        "",
        "Respond with ONLY a JSON object of this exact shape:",
        "{",
        '  "terminal_failure_kind": "<one of the enum>",',
        '  "stages": [',
        f"    {example}",
        "  ],",
        '  "root_cause_stage": <int or null>',
        "}",
    ]
    return "\n".join(lines)


def _extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from *text* (fenced or bare)."""
    cleaned = text.strip()
    # Strip a single surrounding code fence.
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
        # Fall back to the outermost {...} span.
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise CausalAnalysisError("response contains no JSON object") from None
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise CausalAnalysisError(f"invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise CausalAnalysisError("response JSON is not an object")
    return parsed


def _validate_attribution(attr: Any, expected_stage_index: int) -> dict[str, Any]:
    """Validate one stage attribution dict; return the cleaned fields."""
    if not isinstance(attr, dict):
        raise CausalAnalysisError(f"stage attribution {expected_stage_index} is not an object")
    terminal_cause = attr.get("terminal_cause")
    criticality = attr.get("criticality")
    agent_mechanism = attr.get("agent_mechanism")
    if not isinstance(terminal_cause, str) or not terminal_cause:
        raise CausalAnalysisError(f"stage {expected_stage_index} missing terminal_cause")
    if not isinstance(agent_mechanism, str) or not agent_mechanism:
        raise CausalAnalysisError(f"stage {expected_stage_index} missing agent_mechanism")
    if criticality not in CRITICALITY_RANK:
        raise CausalAnalysisError(
            f"stage {expected_stage_index} invalid criticality: {criticality!r}"
        )
    if not is_signature_token(terminal_cause):
        raise CausalAnalysisError(
            f"stage {expected_stage_index} terminal_cause not snake_case: {terminal_cause!r}"
        )
    if not is_signature_token(agent_mechanism):
        raise CausalAnalysisError(
            f"stage {expected_stage_index} agent_mechanism not snake_case: {agent_mechanism!r}"
        )
    terminal_link = attr.get("terminal_link")
    result: dict[str, Any] = {
        "terminal_cause": terminal_cause,
        "criticality": criticality,
        "agent_mechanism": agent_mechanism,
        "terminal_link": terminal_link if isinstance(terminal_link, str) else None,
    }
    return result


def _apply_attributions(
    stages: list[StageRecord],
    attributions: list[dict[str, Any]],
) -> list[StageRecord]:
    """Rebuild *stages* with LLM attributions applied (re-validated)."""
    by_index: dict[int, dict[str, Any]] = {}
    for attr in attributions:
        idx = attr.get("stage_index")
        if not isinstance(idx, int):
            raise CausalAnalysisError(f"attribution missing integer stage_index: {attr!r}")
        if idx in by_index:
            raise CausalAnalysisError(f"duplicate stage_index: {idx}")
        by_index[idx] = _validate_attribution(attr, idx)

    expected = {s.stage_index for s in stages}
    got = set(by_index)
    if got != expected:
        missing = expected - got
        extra = got - expected
        raise CausalAnalysisError(
            "attribution stage_index mismatch "
            f"missing={missing or '(none)'} extra={extra or '(none)'}"
        )

    rebuilt: list[StageRecord] = []
    for stage in stages:
        merged = {**stage.model_dump(), **by_index[stage.stage_index]}
        rebuilt.append(StageRecord.model_validate(merged))
    return rebuilt


def analyze(
    event: dict[str, Any],
    *,
    llm_call: LlmCall | None = None,
) -> CausalAnalysis:
    """Produce a :class:`CausalAnalysis` for one failed *event*.

    With ``llm_call=None`` returns a degraded analysis (deterministic stages,
    all-``unknown`` attribution). With an LLM, fills attribution per the strict
    JSON contract; any violation raises :class:`CausalAnalysisError`.
    """
    event_id = str(event.get("id") or event.get("event_id") or "")
    steps = normalize_trace_steps(event)
    stages = build_stage_records(steps)
    terminal_failure_kind = classify_terminal_failure(event)

    if llm_call is None or not stages:
        return CausalAnalysis(
            event_id=event_id,
            terminal_failure_kind=terminal_failure_kind,
            stages=stages,
        )

    prompt = build_analysis_prompt(stages, terminal_failure_kind, event_id=event_id)
    raw = llm_call(prompt)
    if not isinstance(raw, str) or not raw.strip():
        raise CausalAnalysisError("llm_call returned empty response")
    payload = _extract_json_object(raw)

    if "stages" not in payload or not isinstance(payload["stages"], list):
        raise CausalAnalysisError("response missing 'stages' list")
    attributions = payload["stages"]

    final_terminal_kind: TerminalFailureKind = terminal_failure_kind
    raw_kind = payload.get("terminal_failure_kind")
    if isinstance(raw_kind, str) and raw_kind in _TERMINAL_KIND_VALUES:
        final_terminal_kind = raw_kind  # type: ignore[assignment]

    filled_stages = _apply_attributions(stages, attributions)

    root_cause_stage: int | None = None
    raw_root = payload.get("root_cause_stage")
    if isinstance(raw_root, int):
        root_cause_stage = raw_root
    elif raw_root is None:
        # Infer the first root_cause stage if the LLM omitted the field.
        for s in filled_stages:
            if s.criticality == "root_cause":
                root_cause_stage = s.stage_index
                break

    return CausalAnalysis(
        event_id=event_id,
        terminal_failure_kind=final_terminal_kind,
        stages=filled_stages,
        root_cause_stage=root_cause_stage,
    )


def pick_root_cause(
    analysis: CausalAnalysis,
) -> tuple[Criticality, str, str] | None:
    """Return the ``(criticality, terminal_cause, agent_mechanism)`` of the
    root-cause stage, or ``None`` if none is attributed."""
    target = analysis.root_cause_stage
    for stage in analysis.stages:
        if stage.stage_index == target and stage.criticality != "unknown":
            return (stage.criticality, stage.terminal_cause, stage.agent_mechanism)
    return None


__all__ = [
    "CausalAnalysisError",
    "LlmCall",
    "analyze",
    "build_analysis_prompt",
    "pick_root_cause",
]
