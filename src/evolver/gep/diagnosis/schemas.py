"""Pydantic schemas for causal diagnosis.

Methodology inspired by Self-Harness (arXiv:2606.09498). No Node.js
equivalent; evolver.py self-research addition (Sprint B1).

The model is terminal-cause-first: a failed ``EvolutionEvent`` trajectory is
segmented into behavioural *stages* (each ending at a "change" step), then an
LLM attributes ``(terminal_cause, criticality, agent_mechanism)`` per stage.
Attribution fields default to "unknown"/empty so ``build_stage_records`` can
produce partial records that the analyzer fills later (see ``causal.py``).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Criticality = Literal[
    "root_cause",
    "contributor",
    "non_terminal_friction",
    "recovered_friction",
    "unknown",
]

TerminalFailureKind = Literal[
    "missing_required_artifact",
    "missing_dependency",
    "agent_timeout",
    "verifier_runtime_error",
    "verifier_assertion",
    "reward_zero",
    "unknown",
]

#: criticality → rank (root_cause first). Used by Sprint B2 clustering.
CRITICALITY_RANK: dict[str, int] = {
    "root_cause": 0,
    "contributor": 1,
    "non_terminal_friction": 2,
    "recovered_friction": 3,
    "unknown": 4,
}

_SIGNATURE_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def is_signature_token(value: str) -> bool:
    """True iff *value* is a non-empty snake_case signature token."""
    return bool(_SIGNATURE_TOKEN_RE.match(value))


class NormalizedStep(BaseModel):
    """One step in a normalized trajectory (deterministic, from trace)."""

    model_config = ConfigDict(extra="forbid")
    index: int
    tool: str = ""
    is_change: bool = False
    summary: str = ""


class StageRecord(BaseModel):
    """A behavioural stage ending at a "change" step.

    ``stage_index`` / ``steps`` / ``summary`` are deterministic (from trace);
    ``terminal_cause`` / ``criticality`` / ``agent_mechanism`` are filled by
    the analyzer (LLM) and default to "unknown"/empty so partial construction
    (pre-analysis) is valid.
    """

    model_config = ConfigDict(extra="forbid")
    stage_index: int
    steps: list[NormalizedStep] = Field(default_factory=list)
    summary: str = ""
    terminal_cause: str = ""
    criticality: Criticality = "unknown"
    agent_mechanism: str = ""
    terminal_link: str | None = None

    @field_validator("terminal_cause", "agent_mechanism")
    @classmethod
    def _signature_token(cls, v: str) -> str:
        # Empty is allowed (pre-analysis); non-empty must be snake_case.
        if v and not is_signature_token(v):
            raise ValueError(f"not a snake_case signature token: {v!r}")
        return v


class CausalAnalysis(BaseModel):
    """The attributed analysis of one failed ``EvolutionEvent``."""

    model_config = ConfigDict(extra="forbid")
    event_id: str
    terminal_failure_kind: TerminalFailureKind = "unknown"
    stages: list[StageRecord] = Field(default_factory=list)
    root_cause_stage: int | None = None
    format: str = "evolver.diagnosis.v0"


__all__ = [
    "CRITICALITY_RANK",
    "CausalAnalysis",
    "Criticality",
    "NormalizedStep",
    "StageRecord",
    "TerminalFailureKind",
    "is_signature_token",
]
