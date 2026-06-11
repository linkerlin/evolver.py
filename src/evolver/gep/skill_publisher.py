"""Skill publisher — publish distilled skills to the ATP marketplace.

Equivalent to Node's ``evolver/src/gep/skillPublisher.js``.

Takes a distilled skill (from :mod:`skill_distiller`) and packages
it as an ATP service listing. The listing includes:
* Skill name + intent as service title / description.
* Trigger phrases as supported operations.
* Heuristics as service capabilities.
* Source hash for deduplication.

The publisher interacts with :mod:`evolver.atp.service_helper` to
register the listing on the Hub.

Design notes
------------
* Wraps :mod:`atp.service_helper` with skill-specific defaults.
* Deduplication: skips publishing if a skill with the same source_hash
  is already listed.
* Respects ``enable_skill_publishing`` feature flag.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evolver.atp.protocol import ServiceListing
from evolver.gep.feature_flags import is_enabled
from evolver.gep.paths import get_workspace_root

logger = logging.getLogger(__name__)

# Default pricing for skill listings
DEFAULT_PRICE_PER_TASK = 0.01


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SkillPublication:
    skill_name: str
    source_hash: str
    service_id: str
    hub_response: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _load_published_hashes(path: Path | None = None) -> set[str]:
    """Load the set of already-published skill hashes."""
    p = path or (get_workspace_root() / "evolver" / ".config" / "published_skills.json")
    if not p.exists():
        return set()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("hashes", []))
    except (OSError, json.JSONDecodeError):
        return set()


def _save_published_hashes(hashes: set[str], path: Path | None = None) -> None:
    """Persist the set of published skill hashes."""
    p = path or (get_workspace_root() / "evolver" / ".config" / "published_skills.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"hashes": sorted(hashes)}, f, indent=2)
        f.write("\n")
    tmp.replace(p)


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------


def _skill_to_listing(skill: Any) -> ServiceListing:
    """Convert a :class:`skill_distiller.DistilledSkill` to an ATP
    :class:`ServiceListing`.
    """
    from evolver.gep.skill_distiller import DistilledSkill

    if not isinstance(skill, DistilledSkill):
        raise TypeError(f"Expected DistilledSkill, got {type(skill).__name__}")

    capabilities = skill.heuristics[:10]  # cap at 10
    return ServiceListing(
        service_id=f"skill-{skill.source_hash}",
        title=skill.name,
        description=skill.intent,
        capabilities=capabilities,
        price_per_task=DEFAULT_PRICE_PER_TASK,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def publish_skill(
    skill: Any,
    *,
    hub_client: Any | None = None,
    dedup_path: Path | None = None,
    _publish_fn: Any | None = None,
) -> SkillPublication | None:
    """Publish *skill* to the ATP marketplace.

    If *hub_client* is omitted, the function constructs a default
    :class:`evolver.atp.hub_client.HubClient`.

    Returns :class:`SkillPublication` on success, or ``None`` if
    the skill was already published or the feature flag is off.
    """
    if not is_enabled("enable_skill_publishing"):
        logger.info("[SkillPublisher] Feature flag disabled — skipping publish")
        return None

    from evolver.gep.skill_distiller import DistilledSkill

    if not isinstance(skill, DistilledSkill):
        logger.warning("[SkillPublisher] Expected DistilledSkill, got %s", type(skill).__name__)
        return None

    # Deduplication
    published = _load_published_hashes(dedup_path)
    if skill.source_hash in published:
        logger.info("[SkillPublisher] Skill already published: %s", skill.name)
        return None

    listing = _skill_to_listing(skill)

    publish_fn = _publish_fn
    if publish_fn is None:
        # Lazy import to avoid circular deps
        try:
            from evolver.atp.service_helper import publish as _real_publish

            publish_fn = _real_publish
        except ImportError:
            logger.warning("[SkillPublisher] ATP service_helper not available")
            return None

    try:
        if _publish_fn is not None:
            result: dict[str, Any] = _publish_fn(
                title=listing.title,
                description=listing.description,
                capabilities=listing.capabilities,
                price_per_task=listing.price_per_task,
            )
        else:
            import asyncio

            result = asyncio.run(
                publish_fn(
                    title=listing.title,
                    description=listing.description,
                    capabilities=listing.capabilities,
                    price_per_task=listing.price_per_task,
                )
            )
        published.add(skill.source_hash)
        _save_published_hashes(published, dedup_path)
        logger.info("[SkillPublisher] Published skill %s as %s", skill.name, listing.service_id)
        return SkillPublication(
            skill_name=skill.name,
            source_hash=skill.source_hash,
            service_id=listing.service_id,
            hub_response=result,
        )
    except Exception as exc:
        logger.warning("[SkillPublisher] Failed to publish skill %s: %s", skill.name, exc)
        return None


def list_publishable_skills(
    *,
    skill_dir: Path | None = None,
    dedup_path: Path | None = None,
) -> list[Any]:
    """Scan *skill_dir* and return skills that have not been published yet."""
    from evolver.gep.skill2gep import skill_to_gene
    from evolver.gep.skill_distiller import DistilledSkill

    root = get_workspace_root()
    out = skill_dir or (root / "evolver" / "skills")
    published = _load_published_hashes(dedup_path)
    unpublished: list[Any] = []

    if not out.exists():
        return unpublished

    for md_file in out.rglob("*.md"):
        gene = skill_to_gene(md_file)
        if gene is None:
            continue
        # Reconstruct a minimal DistilledSkill for publishing
        try:
            text = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        if source_hash in published:
            continue
        # Build a synthetic DistilledSkill from the Markdown content
        skill = DistilledSkill(
            name=gene.name,
            intent=gene.intent,
            triggers=gene.trigger_phrases,
            heuristics=gene.signal_keywords,
            examples=[],
            source_hash=source_hash,
        )
        unpublished.append(skill)

    return unpublished
