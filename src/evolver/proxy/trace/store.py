"""In-memory request trace ring buffer for the A2A Proxy.

Equivalent to trace bookkeeping in ``evolver/src/proxy/trace/``.
"""

from __future__ import annotations

import time
from typing import Any

_DEFAULT_MAX = 100


class TraceStore:
    """Ring buffer of recent proxy/Hub request traces."""

    def __init__(self, max_entries: int = _DEFAULT_MAX) -> None:
        self._max = max(1, max_entries)
        self._entries: list[dict[str, Any]] = []

    def push(self, entry: dict[str, Any]) -> None:
        if "ts" not in entry:
            entry = {**entry, "ts": time.time()}
        self._entries.append(entry)
        while len(self._entries) > self._max:
            self._entries.pop(0)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        cap = max(1, limit)
        return self._entries[-cap:]

    def count(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()


_default_store = TraceStore()


def get_trace_store() -> TraceStore:
    return _default_store


__all__ = ["TraceStore", "get_trace_store"]
