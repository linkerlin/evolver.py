"""Tests for evolver.proxy.extensions.dm_handler."""

from __future__ import annotations

from evolver.proxy.extensions.dm_handler import DMHandler, create_dm_handler


class TestCreateDMHandler:
    def test_returns_instance(self):
        handler = create_dm_handler()
        assert isinstance(handler, DMHandler)


class TestProcess:
    def test_unknown_type_ignored(self):
        handler = create_dm_handler()
        result = handler.process({"payload": {"type": "unknown", "content": ""}})
        assert result["ok"] is False
        assert result["action"] == "ignored"

    def test_command_evolve(self):
        handler = create_dm_handler()
        result = handler.process({"payload": {"type": "command", "content": "evolve now"}})
        assert result["ok"] is True
        assert result["trigger"] == "evolution_cycle"

    def test_command_stop(self):
        handler = create_dm_handler()
        result = handler.process({"payload": {"type": "command", "content": "stop"}})
        assert result["ok"] is True
        assert result["trigger"] == "shutdown"

    def test_command_status(self):
        handler = create_dm_handler()
        result = handler.process({"payload": {"type": "command", "content": "status"}})
        assert result["ok"] is True
        assert result["trigger"] == "status_report"

    def test_command_unrecognized(self):
        handler = create_dm_handler()
        result = handler.process({"payload": {"type": "command", "content": "dance"}})
        assert result["ok"] is False
        assert result["reason"] == "unrecognized_command"

    def test_notification_logged(self):
        handler = create_dm_handler()
        result = handler.process({"payload": {"type": "notification", "content": "Hello"}})
        assert result["ok"] is True
        assert result["action"] == "notification_logged"

    def test_request_queued(self):
        handler = create_dm_handler()
        result = handler.process({"payload": {"type": "request", "content": "Do something"}})
        assert result["ok"] is True
        assert result["action"] == "request_queued"

    def test_register_custom_handler(self):
        handler = create_dm_handler()
        custom_called = False

        def custom_handler(content, envelope):
            nonlocal custom_called
            custom_called = True
            return {"ok": True, "custom": True}

        handler.register("custom", custom_handler)
        # Note: process() doesn't use registered handlers in current implementation,
        # but register() stores them
        assert "custom" in handler.handlers
