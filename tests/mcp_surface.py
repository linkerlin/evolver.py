"""Closed FSM MCP surface the host is allowed to see (算子即基因 P1-1).

In ``IDLE`` state, ``tools/list`` exposes ``evolve_begin`` + ``evolve_status``
(plus read-only record/asset lookup helpers) and hides ``run_lens`` and
``evolve_settle``.

In ``ACTIVE_RUN`` state, ``tools/list`` hides ``evolve_begin`` and exposes
``run_lens`` + ``evolve_settle`` + ``evolve_status`` (plus read-only helpers).
"""

from __future__ import annotations

MCP_READONLY_AUX_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "episode_get",
        "episode_inspect",
        "tool_asset_search",
        "tool_asset_get",
        "tool_cycle_timeline",
    }
)

MCP_IDLE_TOOL_NAMES: frozenset[str] = (
    frozenset({"evolve_begin", "evolve_status"}) | MCP_READONLY_AUX_TOOL_NAMES
)

MCP_ACTIVE_TOOL_NAMES: frozenset[str] = (
    frozenset({"run_lens", "evolve_settle", "evolve_status"}) | MCP_READONLY_AUX_TOOL_NAMES
)

MCP_ALL_TOOL_NAMES: frozenset[str] = MCP_IDLE_TOOL_NAMES | MCP_ACTIVE_TOOL_NAMES

#: Default connect-time catalog when workspace is IDLE.
MCP_TOOL_NAMES: frozenset[str] = MCP_IDLE_TOOL_NAMES

MCP_PROMPT_NAMES: frozenset[str] = frozenset({"evolver_swarm"})

MCP_RESOURCE_URIS: frozenset[str] = frozenset(
    {
        "evolver://status",
        "evolver://instrument-prompt",
        "evolver://dispatch/last",
        "evolver://events/recent",
    }
)
