"""Dual-direction record route (经验即证据 §5.6, shadow only) + Harness2 INV x DOM scoping.

SelfSearch's two lineages (capability / adaptive) share episode records: each
direction's improver reads the other's records, so a tool discovered under one
direction is visible to the other — without scoring either direction. This
module is the **shadow form**: two directions run in parallel, each producing
a content-addressed record, each direction's context including the other's
records. No winner is chosen; the archive keeps both.

Harness2 (arXiv:2610.14224v1 §3.2) strengthens parallel specialization via
orthogonal scope separation:
- ``INV`` (Invariant / Process Scope, mapped to ``capability`` / ``dimension="tool"``):
  owns workflow rules, deterministic verification scripts (``scripts/``),
  tool-loop hooks (``plugin/``, ``hooks/``), and general tool skills.
- ``DOM`` (Domain / Practitioner Scope, mapped to ``adaptive`` / ``dimension="content"``):
  owns domain reconciliation rules, deliverable contracts, domain skills, and
  domain code modules.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from evolver.gep import episode_record

#: The two qualitative search directions (SelfSearch §2, "Search across
#: generations"). Capability expands reusable tools; adaptive improves how the
#: improver revises its approach. They share records; they are not scored.
DIRECTIONS: Final = ("capability", "adaptive")

#: Harness2 (§3.2) orthogonal proposer roles.
SCOPED_ROLES: Final = ("INV", "DOM")

DIRECTION_TO_SCOPE_ROLE: Final[dict[str, str]] = {
    "capability": "INV",
    "adaptive": "DOM",
}
SCOPE_ROLE_TO_DIRECTION: Final[dict[str, str]] = {
    "INV": "capability",
    "DOM": "adaptive",
}
SCOPE_ROLE_TO_DIMENSION: Final[dict[str, str]] = {
    "INV": "tool",
    "DOM": "content",
}


def other_direction(direction: str) -> str:
    """The direction a given direction shares records with."""
    if direction not in DIRECTIONS:
        raise ValueError(f"unknown direction: {direction!r}")
    return "adaptive" if direction == "capability" else "capability"


def normalize_scope_role(role_or_direction: str) -> str:
    """Normalize ``'INV' | 'DOM' | 'capability' | 'adaptive'`` to ``'INV' | 'DOM'``."""
    raw = str(role_or_direction or "").strip()
    upper = raw.upper()
    if upper in SCOPED_ROLES:
        return upper
    if raw in DIRECTION_TO_SCOPE_ROLE:
        return DIRECTION_TO_SCOPE_ROLE[raw]
    raise ValueError(f"unknown scope role or direction: {role_or_direction!r}")


def _is_inv_path(norm_path: str) -> bool:
    """True when *norm_path* belongs to the Invariant / Process / Tool surface."""
    lower = norm_path.lower()
    base = norm_path.rsplit("/", 1)[-1]
    if (
        lower.startswith(("scripts/", "bin/", "plugin/", "hooks/", ".agents/hooks/"))
        or "/scripts/" in f"/{lower}"
        or "/plugin/" in f"/{lower}"
        or "/hooks/" in f"/{lower}"
    ):
        return True
    if base in {"AGENTS.md", "CLAUDE.md", "guardrails.md", "systemprompt.md"}:
        return True
    if ("/skills/" in f"/{lower}" or base == "SKILL.md") and (
        "tool" in lower
        or "check" in lower
        or "verify" in lower
        or "inv" in lower
        or "lint" in lower
    ):
        return True
    return any(
        token in lower
        for token in ("validator", "gate", "inspect", "workflow", "tool", "policy", "check")
    )


def _is_dom_forbidden_path(norm_path: str) -> bool:
    """True when *norm_path* is strictly process/runtime machinery off-limits to DOM."""
    lower = norm_path.lower()
    return (
        lower.startswith(("scripts/", "bin/", "plugin/", "hooks/", ".agents/hooks/"))
        or "/scripts/" in f"/{lower}"
        or "/plugin/" in f"/{lower}"
        or "/hooks/" in f"/{lower}"
    )


def validate_proposal_scope(
    role_or_direction: str,
    touched_files: Sequence[str],
) -> dict[str, Any]:
    """Check whether *touched_files* respect the ``INV`` vs ``DOM`` scope boundary.

    - ``INV`` (Invariant / Process) may edit ``scripts/``, ``plugin/``, ``hooks/``,
      workflow/validator surfaces, and tool-oriented skills, but must not edit
      domain business modules.
    - ``DOM`` (Domain / Practitioner) may edit domain modules, domain skills,
      and deliverable rules, but must not edit ``scripts/``, ``plugin/``, or
      ``hooks/`` runtime machinery.
    """
    role = normalize_scope_role(role_or_direction)
    direction = SCOPE_ROLE_TO_DIRECTION[role]
    dimension = SCOPE_ROLE_TO_DIMENSION[role]
    allowed: list[str] = []
    out_of_scope: list[str] = []

    for raw in touched_files:
        norm = str(raw or "").replace("\\", "/").strip("/")
        if not norm:
            continue
        if role == "INV":
            if _is_inv_path(norm):
                allowed.append(norm)
            else:
                out_of_scope.append(norm)
        elif not _is_dom_forbidden_path(norm):
            allowed.append(norm)
        else:
            out_of_scope.append(norm)

    return {
        "ok": len(out_of_scope) == 0,
        "role": role,
        "direction": direction,
        "dimension": dimension,
        "allowed_files": allowed,
        "out_of_scope_files": out_of_scope,
    }


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


def build_scoped_direction_prompt(
    role_or_direction: str,
    own_record: dict[str, Any],
    other_record: dict[str, Any],
) -> str:
    """Render a direction block augmented with Harness2 ``INV x DOM`` scope rules."""
    role = normalize_scope_role(role_or_direction)
    direction = SCOPE_ROLE_TO_DIRECTION[role]
    dimension = SCOPE_ROLE_TO_DIMENSION[role]
    base_block = build_direction_block(direction, own_record, other_record)
    if role == "INV":
        scope_note = (
            "- scope_role: `INV` (Invariant / Process, dimension=`tool`) — own "
            "verification scripts (`scripts/`), tool-loop hooks (`plugin/`), and "
            "workflow/inspection tools; do NOT modify domain business logic."
        )
    else:
        scope_note = (
            "- scope_role: `DOM` (Domain / Practitioner, dimension=`content`) — own "
            "domain reconciliation rules, deliverable contracts, and domain skills; "
            "do NOT modify runtime `scripts/` or `plugin/` hooks."
        )
    return f"{base_block}\n{scope_note}\n- hypothesis_dimension: `{dimension}`"


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
    "DIRECTION_TO_SCOPE_ROLE",
    "SCOPED_ROLES",
    "SCOPE_ROLE_TO_DIMENSION",
    "SCOPE_ROLE_TO_DIRECTION",
    "build_direction_block",
    "build_scoped_direction_prompt",
    "normalize_scope_role",
    "other_direction",
    "run_dual_record_route",
    "validate_proposal_scope",
]
