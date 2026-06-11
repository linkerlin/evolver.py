"""Proxy trace subsystem — request ring buffer and diagnostics."""

from __future__ import annotations

from evolver.proxy.trace.store import TraceStore, get_trace_store

__all__ = ["TraceStore", "get_trace_store"]
