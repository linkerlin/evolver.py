"""Session handler: manage multi-agent sessions.

Equivalent to evolver/src/proxy/extensions/sessionHandler.js.
"""

from __future__ import annotations

import secrets
import time
from typing import Any


class SessionHandler:
    """Manage agent sessions: create, join, leave, broadcast."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}

    def create(
        self, owner: str | None = None, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        session_id = f"sess_{secrets.token_hex(8)}"
        self._sessions[session_id] = {
            "id": session_id,
            "owner": owner or "anonymous",
            "created_at": time.time(),
            "participants": [owner] if owner else [],
            "messages": [],
            "metadata": metadata or {},
        }
        return {"ok": True, "session_id": session_id}

    def join(self, session_id: str, participant: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            return {"ok": False, "error": "session_not_found"}
        if participant not in session["participants"]:
            session["participants"].append(participant)
        return {"ok": True, "session_id": session_id, "participants": session["participants"]}

    def leave(self, session_id: str, participant: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            return {"ok": False, "error": "session_not_found"}
        if participant in session["participants"]:
            session["participants"].remove(participant)
        return {"ok": True, "session_id": session_id, "participants": session["participants"]}

    def message(self, session_id: str, sender: str, content: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            return {"ok": False, "error": "session_not_found"}
        msg = {
            "id": f"msg_{secrets.token_hex(4)}",
            "sender": sender,
            "content": content,
            "ts": time.time(),
        }
        session["messages"].append(msg)
        return {"ok": True, "session_id": session_id, "message": msg}

    def delegate(
        self, session_id: str, from_participant: str, to_participant: str
    ) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            return {"ok": False, "error": "session_not_found"}
        if session.get("owner") != from_participant:
            return {"ok": False, "error": "not_owner"}
        session["owner"] = to_participant
        return {"ok": True, "session_id": session_id, "new_owner": to_participant}

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        return list(self._sessions.values())


def create_session_handler() -> SessionHandler:
    return SessionHandler()


__all__ = ["SessionHandler", "create_session_handler"]
