"""A2A protocol envelope constants.

Equivalent to evolver/src/gep/schemas/protocol.js.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class A2AEnvelope(BaseModel):
    """Standard GEP-A2A message envelope."""

    model_config = ConfigDict(extra="forbid")

    protocol: str = "gep-a2a"
    protocol_version: str = "1.0.0"
    message_type: str
    message_id: str
    sender_id: str
    timestamp: str
    payload: dict | None = None
