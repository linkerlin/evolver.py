"""MCP server — thin tool surface over existing engine modules.

Concept harvest from Node v2 ``evolver-mcp`` (asset.search/fetch/publish,
gep.build, mailbox.*; behavioral re-implementation, no code copied).
Python-side minimal slice (Sprint 24.7, 演进方案.md §9 概念收割 #5):

- ``asset_search`` / ``asset_get`` — local-first GEP asset lookup
- ``mailbox_send`` / ``mailbox_poll`` / ``mailbox_ack`` — durable
  agent↔daemon messages (reuses the proxy MailboxStore)
- ``rebuild_views`` / ``cycle_timeline`` — Sprint 24.1 event projections

The core engine never calls an LLM through these tools; they expose
read/coordination operations to MCP clients (Claude Code, opencode, ...).
Run with ``evolver mcp`` (stdio transport).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from evolver.proxy.mailbox.store import MailboxStore


def _mailbox_dir() -> Path:
    from evolver.gep.paths import get_repo_root

    root = get_repo_root() or Path.cwd()
    return root / ".evolver" / "proxy-mailbox"


def _mailbox_store() -> MailboxStore:
    return MailboxStore(_mailbox_dir())


# ---------------------------------------------------------------------------
# Assets (local-first; no Hub calls)
# ---------------------------------------------------------------------------


def _local_assets() -> list[tuple[str, dict[str, Any]]]:
    from evolver.gep.asset_store import load_capsules, load_genes

    return [
        *[("gene", g) for g in load_genes()],
        *[("capsule", c) for c in load_capsules()],
    ]


def asset_search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search local Genes/Capsules by substring over id/name/description."""
    needle = query.strip().casefold()
    matches: list[dict[str, Any]] = []
    for kind, asset in _local_assets():
        haystack = " ".join(
            str(asset.get(field) or "")
            for field in ("id", "name", "description", "category", "title")
        ).casefold()
        if needle in haystack:
            matches.append(
                {
                    "type": kind,
                    "id": asset.get("id"),
                    "name": asset.get("name") or asset.get("title"),
                    "description": asset.get("description"),
                }
            )
        if len(matches) >= max(1, limit):
            break
    return matches


def asset_get(asset_id: str) -> dict[str, Any]:
    """Fetch one local asset by id (Gene or Capsule)."""
    for _kind, asset in _local_assets():
        if str(asset.get("id")) == asset_id:
            return dict(asset)
    raise LookupError(f"asset not found locally: {asset_id}")


# ---------------------------------------------------------------------------
# Mailbox (durable agent↔daemon messages)
# ---------------------------------------------------------------------------


def mailbox_send(
    type: str,
    payload: dict[str, Any],
    priority: str = "normal",
) -> dict[str, Any]:
    """Enqueue an outbound mailbox message."""
    if priority not in ("high", "normal", "low"):
        raise ValueError(f"priority must be high|normal|low, got {priority}")
    return _mailbox_store().send(type=type, payload=payload, priority=priority)  # type: ignore[arg-type]


def mailbox_poll(limit: int = 10, direction: str = "inbound") -> list[dict[str, Any]]:
    """Poll mailbox messages (newest first).

    ``direction="inbound"`` reads daemon→agent messages; ``"outbound"``
    lists this side's pending sends (useful when no daemon is pumping).
    """
    store = _mailbox_store()
    if direction == "outbound":
        return [m.to_dict() for m in store.poll_outbound(limit=max(1, limit))]
    if direction != "inbound":
        raise ValueError(f"direction must be inbound|outbound, got {direction}")
    return [m.to_dict() for m in store.poll(limit=max(1, limit))]


def mailbox_ack(message_ids: list[str]) -> int:
    """Acknowledge processed messages; returns the acked count."""
    return _mailbox_store().ack(message_ids)


# ---------------------------------------------------------------------------
# Event projections (Sprint 24.1)
# ---------------------------------------------------------------------------


def rebuild_views() -> dict[str, Any]:
    """Replay the event log into derived projections and summarize."""
    views = rebuild_projections_safe()
    return {
        "event_count": views["event_count"],
        "genes": len(views["gene_outcomes"]),
        "cycles": len(views["cycle_timeline"]),
        "path": str(views.get("_path") or ""),
    }


def cycle_timeline(limit: int = 20) -> list[dict[str, Any]]:
    """Recent per-run cycle timelines (stage ladder + outcome)."""
    from evolver.gep.asset_store import read_all_events
    from evolver.gep.event_projection import project_events

    timeline = project_events(read_all_events())["cycle_timeline"]
    result: list[dict[str, Any]] = list(timeline)[-max(1, limit) :]
    return result


def rebuild_projections_safe() -> dict[str, Any]:
    from evolver.gep.event_projection import projections_path, rebuild_projections

    views = rebuild_projections()
    views["_path"] = projections_path()
    return views


def build_server() -> Any:
    """Construct the MCP server instance (stdio transport via ``run``)."""
    from mcp.server.mcpserver import MCPServer

    server: Any = MCPServer(
        "evolver",
        instructions=(
            "Evolver self-evolution engine: search/fetch GEP assets "
            "(Genes/Capsules), exchange durable mailbox messages, and read "
            "event-derived evolution analytics."
        ),
    )

    # Typed defs first, registered via decorator *expressions* — keeps mypy
    # strict clean (the mcp package ships no stubs, so @server.tool() is Any).
    def tool_asset_search(query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search local GEP assets (Genes/Capsules) by keyword."""
        return asset_search(query, limit)

    def tool_asset_get(asset_id: str) -> dict[str, Any]:
        """Fetch one local Gene/Capsule by id."""
        return asset_get(asset_id)

    def tool_mailbox_send(
        type: str, payload: dict[str, Any], priority: str = "normal"
    ) -> dict[str, Any]:
        """Send a durable mailbox message to the evolver daemon."""
        return mailbox_send(type, payload, priority)

    def tool_mailbox_poll(limit: int = 10, direction: str = "inbound") -> list[dict[str, Any]]:
        """Poll mailbox messages (direction: inbound|outbound)."""
        return mailbox_poll(limit, direction)

    def tool_mailbox_ack(message_ids: list[str]) -> int:
        """Acknowledge processed mailbox messages."""
        return mailbox_ack(message_ids)

    def tool_rebuild_views() -> dict[str, Any]:
        """Rebuild event-log projections (gene tallies, cycle timelines)."""
        return rebuild_views()

    def tool_cycle_timeline(limit: int = 20) -> list[dict[str, Any]]:
        """Recent evolution cycle timelines derived from the event log."""
        return cycle_timeline(limit)

    register = server.tool()
    for fn in (
        tool_asset_search,
        tool_asset_get,
        tool_mailbox_send,
        tool_mailbox_poll,
        tool_mailbox_ack,
        tool_rebuild_views,
        tool_cycle_timeline,
    ):
        register(fn)

    return server


def main() -> int:
    """Entry point for ``evolver mcp`` — stdio transport."""
    build_server().run(transport="stdio")
    return 0


__all__ = [
    "asset_get",
    "asset_search",
    "build_server",
    "cycle_timeline",
    "mailbox_ack",
    "mailbox_poll",
    "mailbox_send",
    "main",
    "rebuild_views",
]
