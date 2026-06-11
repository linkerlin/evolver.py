"""Tests for evolver.proxy.trace.store."""

from __future__ import annotations

from evolver.proxy.trace.store import TraceStore, get_trace_store


def test_trace_store_ring_buffer() -> None:
    store = TraceStore(max_entries=3)
    store.push({"path": "a"})
    store.push({"path": "b"})
    store.push({"path": "c"})
    store.push({"path": "d"})
    assert store.count() == 3
    recent = store.recent(10)
    assert [e["path"] for e in recent] == ["b", "c", "d"]


def test_trace_store_clear() -> None:
    store = TraceStore()
    store.push({"path": "x"})
    store.clear()
    assert store.count() == 0


def test_get_trace_store_singleton() -> None:
    a = get_trace_store()
    b = get_trace_store()
    assert a is b
