"""Pydantic schemas for the acceptance gate.

Methodology inspired by Self-Harness (arXiv:2606.09498). No Node.js
equivalent; evolver.py self-research addition (Sprint A1).

The gate evaluates a list of *evaluation layers*. ``held_in`` (the triggering
cluster's representative cases) must improve; each held-out tier (T0/T1/T2)
must not regress. Self-Harness's two-split gate is the special case where the
only held-out layer is T0.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LayerKind = Literal["held_in", "T0_frozen", "T1_semantic", "T2_synthetic"]

#: Verdicts for rate-based layers (held_in / T0).
RateVerdict = Literal["improved", "dropped", "unchanged"]
#: Verdicts for replay/judge layers (T1 / T2).
HoldsVerdict = Literal["holds", "regresses"]
#: T2 may additionally be "unknown" (LLM judge abstained).
T2Verdict = Literal["holds", "regresses", "unknown"]

LayerVerdict = Literal[
    "improved",
    "dropped",
    "unchanged",
    "holds",
    "regresses",
    "unknown",
]

HELD_OUT_TIERS: tuple[LayerKind, ...] = ("T0_frozen", "T1_semantic", "T2_synthetic")
REGRESS_VERDICTS: frozenset[str] = frozenset({"dropped", "regresses"})


class RepeatObs(BaseModel):
    """One repeat observation of a layer's score."""

    model_config = ConfigDict(extra="forbid")
    repeat_index: int
    score: float
    denominator: int | None = None

    @field_validator("score")
    @classmethod
    def _score_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"score must be in [0,1], got {v}")
        return v


class LayerMetric(BaseModel):
    """One evaluation layer's comparison between baseline and candidate."""

    model_config = ConfigDict(extra="forbid")
    layer_id: str
    kind: LayerKind
    baseline_repeats: list[RepeatObs] = Field(default_factory=list)
    candidate_repeats: list[RepeatObs] = Field(default_factory=list)
    baseline_mean: float = 0.0
    candidate_mean: float = 0.0
    delta: float = 0.0
    verdict: LayerVerdict = "unknown"


class AcceptanceResult(BaseModel):
    """The gate's overall decision."""

    model_config = ConfigDict(extra="forbid")
    accepted: bool
    layers: list[LayerMetric] = Field(default_factory=list)
    reason: str
    repeats: int = 1
    format: str = "evolver.acceptance_gate.v0"


__all__ = [
    "AcceptanceResult",
    "HELD_OUT_TIERS",
    "HoldsVerdict",
    "LayerKind",
    "LayerMetric",
    "LayerVerdict",
    "RateVerdict",
    "REGRESS_VERDICTS",
    "RepeatObs",
    "T2Verdict",
]
