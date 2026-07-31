"""Protocol schema — single source of truth for prompt-facing string enums.

Equivalent to evolver/src/gep/schemas/protocol.js.

Enums referenced both in validation code and in the LLM prompt MUST live here
(or be re-exported here). Never hardcode category/outcome/risk/trace enums in
prompt.py.
"""

from __future__ import annotations

from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict

from evolver.gep.schemas.capsule import VALID_OUTCOME_STATUSES
from evolver.gep.schemas.gene import (
    VALID_CATEGORIES,
    VALID_REASONING_LEVELS,
    VALID_ROUTING_TIERS,
    VALID_TOOL_POLICY_SEVERITIES,
)

VALID_RISK_LEVELS: list[str] = ["low", "medium", "high"]
VALID_TRACE_STAGES: list[str] = ["build", "validate", "canary"]


def render_enum(arr: Sequence[str]) -> str:
    """Format an enum array as a pipe-joined string for prompt schemas.

    Example: ``['repair', 'optimize', ...]`` → ``'repair|optimize|...'``
    """
    return "|".join(arr)


def render_enum_list(arr: Sequence[str]) -> str:
    """Format an enum array as a quoted JSON-ish list for prompt schemas.

    Example: ``['build', 'validate', 'canary']`` → ``'"build","validate","canary"'``
    """
    return ",".join(f'"{s}"' for s in arr)


class A2AEnvelope(BaseModel):
    """Standard GEP-A2A message envelope."""

    model_config = ConfigDict(extra="forbid")

    protocol: str = "gep-a2a"
    protocol_version: str = "1.0.0"
    message_type: str
    message_id: str
    sender_id: str
    timestamp: str
    payload: dict[str, Any] | None = None


__all__ = [
    "A2AEnvelope",
    "VALID_CATEGORIES",
    "VALID_OUTCOME_STATUSES",
    "VALID_REASONING_LEVELS",
    "VALID_RISK_LEVELS",
    "VALID_ROUTING_TIERS",
    "VALID_TOOL_POLICY_SEVERITIES",
    "VALID_TRACE_STAGES",
    "render_enum",
    "render_enum_list",
]
