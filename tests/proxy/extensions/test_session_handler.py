"""Tests for evolver.proxy.extensions.session_handler."""

from __future__ import annotations

from evolver.proxy.extensions.session_handler import SessionHandler, create_session_handler


class TestCreateSessionHandler:
    def test_returns_instance(self):
        handler = create_session_handler()
        assert isinstance(handler, SessionHandler)


class TestCreate:
    def test_creates_session(self):
        handler = create_session_handler()
        result = handler.create()
        assert result["ok"] is True
        assert result["session_id"].startswith("sess_")

    def test_creates_with_owner(self):
        handler = create_session_handler()
        result = handler.create(owner="alice")
        session = handler.get_session(result["session_id"])
        assert session is not None
        assert session["owner"] == "alice"
        assert "alice" in session["participants"]

    def test_creates_with_metadata(self):
        handler = create_session_handler()
        result = handler.create(metadata={"project": "test"})
        session = handler.get_session(result["session_id"])
        assert session is not None
        assert session["metadata"]["project"] == "test"


class TestJoin:
    def test_join_existing(self):
        handler = create_session_handler()
        create_result = handler.create()
        sid = create_result["session_id"]
        result = handler.join(sid, "bob")
        assert result["ok"] is True
        assert "bob" in result["participants"]

    def test_join_nonexistent(self):
        handler = create_session_handler()
        result = handler.join("sess_nonexistent", "bob")
        assert result["ok"] is False
        assert result["error"] == "session_not_found"

    def test_no_duplicate_participants(self):
        handler = create_session_handler()
        create_result = handler.create(owner="alice")
        sid = create_result["session_id"]
        handler.join(sid, "alice")
        handler.join(sid, "alice")
        session = handler.get_session(sid)
        assert session["participants"].count("alice") == 1


class TestLeave:
    def test_leave_existing(self):
        handler = create_session_handler()
        create_result = handler.create(owner="alice")
        sid = create_result["session_id"]
        handler.join(sid, "bob")
        result = handler.leave(sid, "bob")
        assert result["ok"] is True
        assert "bob" not in result["participants"]

    def test_leave_nonexistent(self):
        handler = create_session_handler()
        result = handler.leave("sess_nonexistent", "bob")
        assert result["ok"] is False
        assert result["error"] == "session_not_found"


class TestMessage:
    def test_message_existing(self):
        handler = create_session_handler()
        create_result = handler.create(owner="alice")
        sid = create_result["session_id"]
        result = handler.message(sid, "alice", "Hello")
        assert result["ok"] is True
        assert result["message"]["sender"] == "alice"
        assert result["message"]["content"] == "Hello"
        assert "id" in result["message"]
        assert "ts" in result["message"]

    def test_message_nonexistent(self):
        handler = create_session_handler()
        result = handler.message("sess_nonexistent", "alice", "Hello")
        assert result["ok"] is False
        assert result["error"] == "session_not_found"


class TestDelegate:
    def test_delegate_by_owner(self):
        handler = create_session_handler()
        create_result = handler.create(owner="alice")
        sid = create_result["session_id"]
        handler.join(sid, "bob")
        result = handler.delegate(sid, "alice", "bob")
        assert result["ok"] is True
        assert result["new_owner"] == "bob"
        session = handler.get_session(sid)
        assert session["owner"] == "bob"

    def test_delegate_by_non_owner(self):
        handler = create_session_handler()
        create_result = handler.create(owner="alice")
        sid = create_result["session_id"]
        handler.join(sid, "bob")
        result = handler.delegate(sid, "bob", "alice")
        assert result["ok"] is False
        assert result["error"] == "not_owner"

    def test_delegate_nonexistent(self):
        handler = create_session_handler()
        result = handler.delegate("sess_nonexistent", "alice", "bob")
        assert result["ok"] is False
        assert result["error"] == "session_not_found"


class TestListSessions:
    def test_empty(self):
        handler = create_session_handler()
        assert handler.list_sessions() == []

    def test_multiple(self):
        handler = create_session_handler()
        handler.create()
        handler.create()
        assert len(handler.list_sessions()) == 2
