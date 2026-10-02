"""Dual-direction record route (经验即证据 §5.6, shadow only).

SelfSearch's two lineages (capability / adaptive) share episode records: each
direction's improver reads the other's records, so a tool discovered under one
direction is visible to the other — without scoring either direction. This
module is the **shadow form**: two directions run in parallel, each producing
a content-addressed record, each direction's context including the other's
records. No winner is chosen; the archive keeps both.

NOT population optimization: ``MULTI_PROPOSE_ROUTES`` stays 1. This is the
record route (records shared), not the selection route (a winner chosen) —
the two are deliberately separate, and only the record route is shadowed here.

The production form (LLM-driven dual lineages over real episodes) is a later
step; this shadow validates the sharing mechanism end to end.
"""

from __future__ import annotations

from typing import Any, Final

from evolver.gep import episode_record

#: The two qualitative search directions (SelfSearch §2, "Search across
#: generations"). Capability expands reusable tools; adaptive improves how the
#: improver revises its approach. They share records; they are not scored.
DIRECTIONS: Final = ("capability", "adaptive")


def other_direction(direction: str) -> str:
    """The direction a given direction shares records with."""
    if direction not in DIRECTIONS:
        raise ValueError(f"unknown direction: {direction!r}")
    return "adaptive" if direction == "capability" else "capability"


def build_direction_block(
    direction: str,
    own_record: dict[str, Any],
    other_record: dict[str, Any],
) -> str:
    """Render one direction's record context: its own record + the OTHER's.

    Record sharing is the point — each direction sees what the other produced,
    so discoveries transfer without either direction being scored against the
    other. The block cites records by content address, so the improver can
    fetch the full body by id.
    """
    other = other_direction(direction)
    return "\n".join(
        [
            f"## Self-improvement records (direction: {direction})",
            f"- own ({direction}): `{own_record.get('id')}`",
            f"- other ({other}): `{other_record.get('id')}`",
            "Read the other direction's record by id before revising — a tool "
            "discovered there is visible to you without either direction "
            "being scored.",
        ]
    )


def run_dual_record_route(
    capability_scene: dict[str, Any],
    adaptive_scene: dict[str, Any],
) -> dict[str, Any]:
    """Run both directions in parallel, each producing a record that sees the other's.

    Shadow: two records (one per direction), each written through the normal
    content-addressed store, each direction's context including the other's
    record. No scoring, archive kept — the two records coexist.
    """
    capability = episode_record.record_episode(episode_record.build_episode(capability_scene))
    adaptive = episode_record.record_episode(episode_record.build_episode(adaptive_scene))
    return {
        "capability_record": capability,
        "adaptive_record": adaptive,
        "capability_context": build_direction_block("capability", capability, adaptive),
        "adaptive_context": build_direction_block("adaptive", adaptive, capability),
    }


__all__ = [
    "DIRECTIONS",
    "build_direction_block",
    "other_direction",
    "run_dual_record_route",
]
