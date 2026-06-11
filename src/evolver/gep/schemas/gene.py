"""Gene schema — single source of truth for the Gene object shape.

Equivalent to evolver/src/gep/schemas/gene.js.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

VALID_CATEGORIES = ["repair", "optimize", "innovate", "explore"]
VALID_ROUTING_TIERS = ["cheap", "mid", "expensive"]
VALID_REASONING_LEVELS = ["off", "low", "medium", "high"]
VALID_TOOL_POLICY_SEVERITIES = ["warn", "block"]


class RoutingHint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tier: Literal["cheap", "mid", "expensive"] | None = None
    reasoning_level: Literal["off", "low", "medium", "high"] | None = None


class ToolPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allow_only: list[str] | None = None
    deny: list[str] | None = None
    severity: Literal["warn", "block"] = "warn"


class Constraints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_files: int = 20
    forbidden_paths: list[str] = Field(default_factory=lambda: [".git", "node_modules"])


class Gene(BaseModel):
    """Gene model equivalent to Node GEP Gene schema."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    type: Literal["Gene"] = "Gene"
    id: str | None = None
    category: Literal["repair", "optimize", "innovate", "explore"] = "innovate"
    signals_match: list[str] = Field(default_factory=list)
    strategy: list[str] = Field(default_factory=list)
    validation: list[str] = Field(default_factory=list)
    constraints: Constraints = Field(default_factory=Constraints)
    preconditions: list[str] = Field(default_factory=list)
    summary: str = ""
    schema_version: str = "1.6.0"
    epigenetic_marks: list[str] = Field(default_factory=list)
    learning_history: list[dict[str, Any]] = Field(default_factory=list)
    anti_patterns: list[str] = Field(default_factory=list)
    routing_hint: RoutingHint | None = None
    tool_policy: ToolPolicy | None = None
    asset_id: str | None = None

    @field_validator("category")
    @classmethod
    def _validate_category(cls, v: str) -> str:
        if v not in VALID_CATEGORIES:
            return "innovate"
        return v


GENE_DEFAULTS = Gene().model_dump()


def create_gene(partial: dict[str, Any] | None = None) -> Gene:
    """Create a Gene with defaults, normalizing malformed fields."""
    partial = dict(partial or {})
    cat = partial.get("category")
    if cat not in VALID_CATEGORIES:
        partial["category"] = "innovate"
    return Gene.model_validate(partial)


def validate_gene(g: Gene) -> bool:
    """Throw (ValidationError) if required fields are missing or malformed."""
    if not g.id:
        raise ValueError("Gene.id is required and must be a string")
    if g.category not in VALID_CATEGORIES:
        raise ValueError(
            f"Gene.category must be one of: {', '.join(VALID_CATEGORIES)}, got: {g.category}"
        )
    return True
