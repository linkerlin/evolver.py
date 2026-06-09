"""Capsule schema — single source of truth for the Capsule object shape.

Equivalent to evolver/src/gep/schemas/capsule.js.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

VALID_OUTCOME_STATUSES = ["success", "failed"]
VALID_SOURCE_TYPES = ["generated", "reused", "reference", "user_authored"]
VALID_VISIBILITIES = ["private", "unlisted", "public"]
VALID_COST_TIERS = ["cheap", "standard", "premium"]

SCHEMA_VERSION = "1.8.0"


class Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["success", "failed"] = "failed"
    score: float = 0.0


class BlastRadius(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: int = 0
    lines: int = 0


class A2AInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    eligible_to_broadcast: bool = False


class DerivationTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_tokens: float = 0
    output_tokens: float = 0
    total_tokens: float = 0
    basis: str = "measured"


class Author(BaseModel):
    model_config = ConfigDict(extra="forbid")
    handle: str
    evox_install_id: str


class Capsule(BaseModel):
    """Capsule model equivalent to Node GEP Capsule schema."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    type: Literal["Capsule"] = "Capsule"
    id: str | None = None
    schema_version: str = SCHEMA_VERSION
    trigger: list[str] = Field(default_factory=list)
    gene: str | None = None
    summary: str = ""
    confidence: float = 0.0
    blast_radius: BlastRadius = Field(default_factory=BlastRadius)
    outcome: Outcome = Field(default_factory=Outcome)
    success_streak: int = 0
    success_reason: str | None = None
    gene_library_version: str | None = None
    env_fingerprint: str | None = None
    source_type: Literal["generated", "reused", "reference", "user_authored"] | None = None
    reused_asset_id: str | None = None
    derivation_tokens: DerivationTokens | None = None
    a2a: A2AInfo = Field(default_factory=A2AInfo)
    content: str | None = None
    diff: str | None = None
    strategy: list[str] = Field(default_factory=list)
    execution_trace: list[dict] = Field(default_factory=list)
    asset_id: str | None = None
    visibility: Literal["private", "unlisted", "public"] | None = None
    scope: list[str] | None = None
    cost_tier: Literal["cheap", "standard", "premium"] | None = None
    pack_of: list[str] | None = None
    author: Author | None = None

    @field_validator("visibility", "cost_tier", mode="before")
    @classmethod
    def _coerce_invalid_enum_to_none(cls, v):
        if v is None:
            return None
        return v


CAPSULE_DEFAULTS = Capsule().model_dump()


def create_capsule(partial: dict | None = None) -> Capsule:
    return Capsule.model_validate(partial or {})


def validate_capsule(c: Capsule) -> bool:
    if not c.id:
        raise ValueError("Capsule.id is required and must be a string")
    if c.outcome.status not in VALID_OUTCOME_STATUSES:
        raise ValueError(
            f"Capsule.outcome.status must be one of: {', '.join(VALID_OUTCOME_STATUSES)}, "
            f"got: {c.outcome.status}"
        )
    return True
