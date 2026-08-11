"""Feedback envelope — normalize scalar feedback into typed metadata.

Behavioral port of Node ``src/gep/feedbackEnvelope.js`` (obfuscated at HEAD;
contract from ``test/feedbackEnvelope.test.js``). Turns raw scalar feedback
into an envelope carrying a label, indecision/conflict flags, attention-aware
uncertainty, and an evidence reference, and aggregates batches of envelopes
into a single dominant-label verdict with calibrated uncertainty.

Labels: scalar >= 0.6 ``positive``, <= 0.4 ``negative``, else ``mixed``.
Uncertainty grows toward the midpoint, with low evaluator attention, on
conflict, and on indecision.
"""

from __future__ import annotations

import math
from typing import Any

_LABEL_POSITIVE_GE = 0.6
_LABEL_NEGATIVE_LE = 0.4
_MIDPOINT = 0.5

# Attention-level penalties applied to envelope uncertainty.
_ATTENTION_PENALTY: dict[str, float] = {
    "full": 0.0,
    "limited": 0.15,
    "skimmed": 0.3,
}
_UNKNOWN_ATTENTION_PENALTY = 0.2

# Levels treated as "low attention" for aggregation (dominant label withheld).
_LOW_ATTENTION_LEVELS = frozenset({"limited", "skimmed", "unknown"})


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _scalar_clamp(value: object) -> float:
    """Clamp a raw scalar to [0, 1]; non-finite input becomes 0.5 (Node parity)."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return _MIDPOINT
    try:
        n = float(value)
    except (TypeError, ValueError):
        return _MIDPOINT
    if not math.isfinite(n):
        return _MIDPOINT
    return _clamp01(n)


def _label_for(scalar: float) -> str:
    if scalar >= _LABEL_POSITIVE_GE:
        return "positive"
    if scalar <= _LABEL_NEGATIVE_LE:
        return "negative"
    return "mixed"


def _attention_level(attention: object) -> str:
    if isinstance(attention, dict):
        level = attention.get("level")
        if isinstance(level, str):
            return level
    return "unknown"


def _envelope_uncertainty(
    scalar: float, attention: object, indecision: bool, conflict: bool
) -> float:
    midpoint_penalty = max(0.0, _MIDPOINT - scalar) * 0.3
    attention_penalty = _ATTENTION_PENALTY.get(
        _attention_level(attention), _UNKNOWN_ATTENTION_PENALTY
    )
    indecision_penalty = 0.25 if indecision else 0.0
    conflict_penalty = 0.35 if conflict else 0.0
    return _clamp01(
        0.1 + midpoint_penalty + attention_penalty + indecision_penalty + conflict_penalty
    )


def evidence_ref(kind: str, ref_id: str, opts: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build an evidence reference for an envelope."""
    ref: dict[str, Any] = {"kind": kind, "id": ref_id}
    if isinstance(opts, dict) and opts.get("summary"):
        ref["summary"] = str(opts["summary"])
    return ref


def from_scalar_feedback(data: dict[str, Any]) -> dict[str, Any]:
    """Wrap a raw scalar-feedback row into a typed envelope."""
    scalar = _scalar_clamp(data.get("scalar"))
    label = _label_for(scalar)
    attention = data.get("evaluator_attention")
    conflict = bool(data.get("conflict", False))
    envelope: dict[str, Any] = {
        "priority_axis": str(data.get("priority_axis") or "task_success"),
        "label": label,
        "scalar": scalar,
        "indecision": label == "mixed",
        "conflict": conflict,
        "uncertainty": _envelope_uncertainty(scalar, attention, label == "mixed", conflict),
    }
    if attention is not None:
        envelope["evaluator_attention"] = attention
    if data.get("evidence_ref") is not None:
        envelope["evidence_ref"] = data["evidence_ref"]
    return envelope


def from_outcome_scalar(outcome: dict[str, Any], opts: dict[str, Any]) -> dict[str, Any]:
    """Build an envelope from an outcome record without mutating it.

    ``user_override`` wins over ``score``; the outcome object is never modified.
    """
    effective = outcome.get("user_override")
    if effective is None:
        effective = outcome.get("score")
    return from_scalar_feedback({**opts, "scalar": effective})


def with_conflict(envelope: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *envelope* flagged as conflicted (uncertainty raised)."""
    conflicted = dict(envelope)
    conflicted["conflict"] = True
    conflicted["uncertainty"] = _envelope_uncertainty(
        float(conflicted.get("scalar", _MIDPOINT)),
        conflicted.get("evaluator_attention"),
        bool(conflicted.get("indecision", False)),
        True,
    )
    return conflicted


def aggregate_feedback_envelopes(envelopes: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate envelopes into one dominant-label verdict.

    The dominant label is withheld when any envelope is indecisive, conflicted,
    or low-attention; uncertainty reflects the mean envelope uncertainty plus
    penalties for conflict/indecision and low attention.
    """
    if not envelopes:
        return {"dominant_label": None, "sample_count": 0, "uncertainty": 1.0}

    scalars = [_scalar_clamp(e.get("scalar")) for e in envelopes]
    uncertainties = [float(e.get("uncertainty", 0.0)) for e in envelopes]
    mean_scalar = sum(scalars) / len(scalars)
    mean_uncertainty = sum(uncertainties) / len(uncertainties)

    any_indecision = any(bool(e.get("indecision", False)) for e in envelopes)
    any_conflict = any(bool(e.get("conflict", False)) for e in envelopes)
    any_low_attention = any(
        _attention_level(e.get("evaluator_attention")) in _LOW_ATTENTION_LEVELS for e in envelopes
    )

    dominant_label: str | None = None
    if not (any_indecision or any_conflict or any_low_attention):
        label = _label_for(mean_scalar)
        if label != "mixed":
            dominant_label = label

    uncertainty = _clamp01(
        mean_uncertainty
        + (0.15 if any_indecision or any_conflict else 0.0)
        + (0.2 if any_low_attention else 0.0)
    )
    return {
        "dominant_label": dominant_label,
        "sample_count": len(envelopes),
        "uncertainty": uncertainty,
    }


__all__ = [
    "aggregate_feedback_envelopes",
    "evidence_ref",
    "from_outcome_scalar",
    "from_scalar_feedback",
    "with_conflict",
]
