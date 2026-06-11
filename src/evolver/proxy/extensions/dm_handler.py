"""Direct message handler: process Hub DM events and trigger local actions.

Equivalent to evolver/src/proxy/extensions/dmHandler.js.
"""

from __future__ import annotations

from typing import Any


class DMHandler:
    """Process direct messages from the Hub."""

    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def register(self, msg_type: str, handler: Any) -> None:
        """Register a handler for a DM type."""
        self.handlers[msg_type] = handler

    def process(self, envelope: dict[str, Any]) -> dict[str, Any]:
        """Process an incoming DM envelope.

        Returns a result dict with action taken.
        """
        payload = envelope.get("payload", {})
        dm_type = payload.get("type", "unknown")
        content = payload.get("content", "")

        if dm_type == "command":
            return self._handle_command(content, envelope)
        elif dm_type == "notification":
            return self._handle_notification(content, envelope)
        elif dm_type == "request":
            return self._handle_request(content, envelope)
        else:
            return {"ok": False, "action": "ignored", "reason": f"unknown_dm_type:{dm_type}"}

    def _handle_command(self, content: str, envelope: dict[str, Any]) -> dict[str, Any]:
        """Execute a command-type DM."""
        cmd = content.strip().lower()
        result: dict[str, Any] = {"ok": True, "action": "command_executed", "command": cmd}

        if cmd.startswith("evolve"):
            result["trigger"] = "evolution_cycle"
        elif cmd.startswith("stop"):
            result["trigger"] = "shutdown"
        elif cmd.startswith("status"):
            result["trigger"] = "status_report"
        else:
            result["ok"] = False
            result["reason"] = "unrecognized_command"

        return result

    def _handle_notification(self, content: str, envelope: dict[str, Any]) -> dict[str, Any]:
        """Handle a notification-type DM."""
        return {
            "ok": True,
            "action": "notification_logged",
            "content_preview": content[:200],
        }

    def _handle_request(self, content: str, envelope: dict[str, Any]) -> dict[str, Any]:
        """Handle a request-type DM."""
        return {
            "ok": True,
            "action": "request_queued",
            "content_preview": content[:200],
        }


def create_dm_handler() -> DMHandler:
    """Factory for the default DM handler."""
    return DMHandler()


__all__ = ["DMHandler", "create_dm_handler"]
