"""Task schema — Hub-delivered task normalization.

Equivalent to evolver/src/gep/schemas/task.js.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VALID_TASK_STATUSES = ["open", "claimed", "completed", "expired", "cancelled"]


class Task(BaseModel):
    """Task model equivalent to Node GEP Task schema."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    type: Literal["Task"] = "Task"
    task_id: str | None = None
    title: str = ""
    signals: str = ""
    status: Literal["open", "claimed", "completed", "expired", "cancelled"] = "open"
    claimed_by: str | None = None
    bounty_id: str | None = None
    bounty_amount: float = 0.0
    complexity_score: float | None = None
    historical_completion_rate: float | None = None
    expires_at: str | None = None
    body: str = ""
    description: str = ""
    nonce: str | None = None
    validation_commands: list[str] = Field(default_factory=list)
    result_asset_id: str | None = None
    atp_order_id: str | None = None
    _commitment_deadline: str | None = None
    _worker_pending: bool = False


TASK_DEFAULTS = Task().model_dump()


def create_task(partial: dict | None = None) -> Task:
    return Task.model_validate(partial or {})


def validate_task(t: Task) -> bool:
    if not t.task_id:
        raise ValueError("Task.task_id is required and must be a string")
    if t.status not in VALID_TASK_STATUSES:
        raise ValueError(
            f"Task.status must be one of: {', '.join(VALID_TASK_STATUSES)}, got: {t.status}"
        )
    return True
