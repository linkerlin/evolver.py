"""Message envelope — structured wrapper for Hub-bound proxy messages.

Equivalent to ``evolver/src/proxy/envelope.js``.

Defines the envelope format used by the mailbox store and Hub sync: every
message has a type, timestamp, sender, and payload. The envelope is the
serialization boundary — anything inside ``payload`` is opaque to the
transport layer.
"""

from __future__ import annotations

import time
import uuid
from typing import Any


def create_envelope(
    msg_type: str,
    payload: dict[str, Any],
    *,
    sender: str = "",
    recipient: str = "",
) -> dict[str, Any]:
    """Create a structured message envelope."""
    return {
        "id": str(uuid.uuid4()),
        "type": msg_type,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sender": sender,
        "recipient": recipient,
        "payload": payload,
    }


def validate_envelope(envelope: dict[str, Any]) -> bool:
    """Return True if *envelope* has the required fields."""
    required = {"id", "type", "timestamp", "payload"}
    return required.issubset(envelope.keys())


def unwrap_payload(envelope: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the payload from a valid envelope, or None."""
    if validate_envelope(envelope):
        payload = envelope.get("payload")
        if isinstance(payload, dict):
            return payload
    return None


__all__ = ["create_envelope", "unwrap_payload", "validate_envelope"]
