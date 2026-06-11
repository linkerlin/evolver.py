"""ATP (Agent Transaction Protocol) wire-contract constants and models.

Equivalent to ``evolver/src/atp/protocol.js``.
These values define the enum sets and Pydantic models for verify modes,
routing modes, proof statuses, roles, execution modes, orders, deliveries,
and service listings used across the ATP marketplace.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class VerifyMode(str, Enum):
    strict = "strict"
    lenient = "lenient"
    auto = "auto"


class RoutingMode(str, Enum):
    direct = "direct"
    proxy = "proxy"
    relay = "relay"


class OrderStatus(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    delivered = "delivered"
    verified = "verified"
    settled = "settled"
    disputed = "disputed"
    cancelled = "cancelled"
    refunded = "refunded"


class Role(str, Enum):
    consumer = "consumer"
    merchant = "merchant"
    validator = "validator"
    judge = "judge"


class ServiceCategory(str, Enum):
    skill = "skill"
    compute = "compute"
    data = "data"
    verification = "verification"


class ExecutionMode(str, Enum):
    exclusive = "exclusive"
    open = "open"
    swarm = "swarm"


# Legacy list constants (backward compat)
ATP_VERIFY_MODES: list[str] = ["auto", "ai_judge", "bilateral"]
ATP_VERIFY_ACTIONS: list[str] = ["confirm", "ai_judge"]
ATP_ROUTING_MODES: list[str] = ["fastest", "cheapest", "auction", "swarm"]
ATP_PROOF_STATUSES: list[str] = [
    "pending",
    "submitted",
    "verified",
    "disputed",
    "settled",
    "rejected",
]
ATP_ROLES: list[str] = ["consumer", "merchant", "arbiter"]
ATP_EXECUTION_MODES: list[str] = ["exclusive", "open", "swarm"]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class Order(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str
    service_id: str
    buyer_id: str
    seller_id: str | None = None
    status: OrderStatus = OrderStatus.pending
    budget: float = Field(ge=0)
    requirements: dict[str, Any] = Field(default_factory=dict)
    verify_mode: VerifyMode = VerifyMode.auto
    routing_mode: RoutingMode = RoutingMode.proxy
    created_at: str = ""
    updated_at: str = ""


class Delivery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delivery_id: str
    order_id: str
    asset_id: str
    proof: str = ""
    submitted_at: str = ""


class Proof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proof_id: str
    order_id: str
    status: Literal["pending", "submitted", "verified", "disputed", "settled", "rejected"] = "pending"
    score: float = Field(ge=0.0, le=1.0, default=0.0)
    verifier_id: str | None = None


class Dispute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dispute_id: str
    order_id: str
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: Literal["open", "resolved", "rejected"] = "open"


class Settlement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    settlement_id: str
    order_id: str
    amount: float = Field(ge=0)
    recipient_id: str
    status: Literal["pending", "completed", "failed"] = "pending"


class ServiceListing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_id: str = ""
    title: str = ""
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    price_per_task: float = Field(ge=0, default=0)
    execution_mode: ExecutionMode = ExecutionMode.exclusive
    max_concurrent: int = Field(ge=1, default=3)
    category: ServiceCategory = ServiceCategory.skill


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_price: float = Field(ge=0, default=1)
    max_concurrent_default: int = Field(ge=1, default=3)
    supported_modes: list[str] = Field(default_factory=list)
