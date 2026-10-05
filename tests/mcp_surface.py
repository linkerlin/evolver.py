"""Closed MCP surface the host is allowed to see.

A registered tool that the instrument prompt does not name is a hole: the
host is told to follow that prompt, and a name that exists only in
``tools/list`` is not part of the protocol. Adding a tool means updating
this set and the prompt together.
"""

from __future__ import annotations

MCP_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "tool_asset_search",
        "tool_asset_get",
        "episode_get",
        "tool_mailbox_send",
        "tool_mailbox_poll",
        "tool_mailbox_ack",
        "tool_rebuild_views",
        "tool_cycle_timeline",
        "swarm_boot",
        "swarm_tick",
        "swarm_distill",
        "swarm_hypothesis",
        "swarm_propose",
        "swarm_solidify",
        "swarm_feedback",
        "swarm_report",
        "swarm_status",
        "swarm_approvals",
        "swarm_approval_resolve",
        "swarm_supervise",
        "swarm_hooks",
        "swarm_hook_event",
        "swarm_skills",
        "swarm_workflow_run",
        "swarm_workflow_act",
        "swarm_workflow_status",
    }
)

MCP_PROMPT_NAMES: frozenset[str] = frozenset({"evolver_swarm"})

MCP_RESOURCE_URIS: frozenset[str] = frozenset(
    {
        "evolver://status",
        "evolver://instrument-prompt",
        "evolver://dispatch/last",
        "evolver://events/recent",
    }
)
