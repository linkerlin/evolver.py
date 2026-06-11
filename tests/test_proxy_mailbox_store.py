"""Tests for evolver.proxy.mailbox.store."""

from __future__ import annotations

from pathlib import Path

import pytest

from evolver.proxy.mailbox.store import MailboxStore, _generate_uuidv7

# ---------------------------------------------------------------------------
# UUID v7
# ---------------------------------------------------------------------------


def test_uuidv7_format() -> None:
    u = _generate_uuidv7()
    assert len(u) == 36
    parts = u.split("-")
    assert len(parts) == 5
    assert len(parts[0]) == 8
    assert len(parts[1]) == 4
    assert len(parts[2]) == 4
    assert parts[2][0] == "7"  # version
    assert len(parts[3]) == 4
    assert parts[3][0] in ("8", "9", "a", "b")  # variant 10
    assert len(parts[4]) == 12


def test_uuidv7_time_ordered() -> None:
    u1 = _generate_uuidv7()
    import time

    time.sleep(0.002)  # ensure different millisecond
    u2 = _generate_uuidv7()
    # When timestamps differ, lexicographic order reflects time order
    assert u1 < u2


# ---------------------------------------------------------------------------
# MailboxStore
# ---------------------------------------------------------------------------


@pytest.fixture
def store(temp_workspace: Path) -> MailboxStore:
    return MailboxStore(temp_workspace / "mailbox")


def test_send_and_get(store: MailboxStore) -> None:
    result = store.send(type="test", payload={"x": 1})
    assert result["status"] == "pending"
    msg_id = result["message_id"]
    msg = store.get_by_id(msg_id)
    assert msg is not None
    assert msg.type == "test"
    assert msg.direction == "outbound"
    assert msg.payload == {"x": 1}


def test_write_inbound_idempotent(store: MailboxStore) -> None:
    id_ = store.write_inbound(id="msg-1", type="notify", payload={"a": 1})
    assert id_ == "msg-1"
    # Second write with same id must be ignored
    id2 = store.write_inbound(id="msg-1", type="notify", payload={"a": 2})
    assert id2 == "msg-1"
    msg = store.get_by_id("msg-1")
    assert msg is not None
    assert msg.payload == {"a": 1}


def test_poll_inbound(store: MailboxStore) -> None:
    store.write_inbound(id="m1", type="a", payload={})
    store.write_inbound(id="m2", type="b", payload={})
    msgs = store.poll(limit=10)
    assert len(msgs) == 2
    assert msgs[0].id == "m2"  # newest first


def test_poll_outbound_priority(store: MailboxStore) -> None:
    store.send(type="low", payload={}, priority="low")
    store.send(type="high", payload={}, priority="high")
    store.send(type="normal", payload={}, priority="normal")
    msgs = store.poll_outbound(limit=10)
    assert [m.type for m in msgs] == ["high", "normal", "low"]


def test_ack_removes_from_inbound(store: MailboxStore) -> None:
    store.write_inbound(id="m1", type="a", payload={})
    assert len(store.poll(limit=10)) == 1
    count = store.ack(["m1"])
    assert count == 1
    assert len(store.poll(limit=10)) == 0
    msg = store.get_by_id("m1")
    assert msg is not None
    assert msg.status == "delivered"


def test_update_status_terminal_removes_from_queue(store: MailboxStore) -> None:
    result = store.send(type="t", payload={})
    mid = result["message_id"]
    assert len(store.poll_outbound(limit=10)) == 1
    store.update_status(mid, "synced")
    assert len(store.poll_outbound(limit=10)) == 0


def test_increment_retry(store: MailboxStore) -> None:
    result = store.send(type="t", payload={})
    mid = result["message_id"]
    store.increment_retry(mid, error="timeout")
    msg = store.get_by_id(mid)
    assert msg is not None
    assert msg.retry_count == 1
    assert msg.error == "timeout"


def test_list_filter(store: MailboxStore) -> None:
    store.send(type="a", payload={})
    store.write_inbound(id="i1", type="b", payload={})
    assert len(store.list(direction="outbound")) == 1
    assert len(store.list(direction="inbound")) == 1
    assert len(store.list(type="a")) == 1


def test_count_pending(store: MailboxStore) -> None:
    store.send(type="a", payload={})
    store.send(type="b", payload={})
    store.write_inbound(id="i1", type="c", payload={})
    store.update_status("i1", "delivered")
    assert store.count_pending(direction="outbound") == 2
    assert store.count_pending(direction="inbound") == 0


def test_cursor_and_state(store: MailboxStore) -> None:
    store.set_cursor("inbound:hub", "abc123")
    assert store.get_cursor("inbound:hub") == "abc123"
    store.set_state("node_id", "node_xyz")
    assert store.get_state("node_id") == "node_xyz"


def test_compact(store: MailboxStore) -> None:
    store.send(type="a", payload={})
    store.send(type="b", payload={})
    store.compact()
    # After compact, index should still be valid
    assert store.count_pending() == 2


def test_persistence_rebuild(temp_workspace: Path) -> None:
    path = temp_workspace / "mailbox"
    s1 = MailboxStore(path)
    s1.send(type="persist", payload={"key": "val"})
    s1.write_inbound(id="in1", type="event", payload={"e": 1})
    s1.set_state("test_key", 42)

    # Simulate restart by creating a new store instance
    s2 = MailboxStore(path)
    assert s2.count_pending() == 2
    msg = s2.get_by_id("in1")
    assert msg is not None
    assert msg.payload == {"e": 1}
    assert s2.get_state("test_key") == 42


def test_write_inbound_batch(store: MailboxStore) -> None:
    messages = [
        {"id": "b1", "type": "t1", "payload": {"k": 1}},
        {"id": "b2", "type": "t2", "payload": {"k": 2}},
    ]
    ids = store.write_inbound_batch(messages)
    assert ids == ["b1", "b2"]
    assert store.get_by_id("b1") is not None
    assert store.get_by_id("b2") is not None
