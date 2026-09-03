"""Skill asset bridge — multi-root priority discovery + GEP store sync.

Concept harvest from EvoX's SkillRegistry/SkillMarketplace (Java): project >
user > builtin loading priority, ``.claude/skills`` layout compatibility, and
marketplace-style metadata. The SKILL.md → Gene conversion itself is delegated
to the existing skill2gep layer (``skill_to_gene_dict``); this module adds the
missing discovery + sync path so host-ecosystem skills (Claude Code / ZCode /
agents skills directories) participate in gene selection like any other gene.

Priority (highest wins; a same-name skill at a lower level is shadowed):

  project  ``<workspace>/.agents/skills`` and ``<workspace>/.claude/skills``
  user     ``~/.agents/skills``, ``~/.zcode/skills``, ``~/.claude/skills``
  builtin  ``<repo>/src/evolver/assets/skills`` (only if present)

``EVOLVER_SKILL_ROOTS`` (os.pathsep-separated, ordered) replaces the defaults.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Final

from evolver.gep.skill2gep import parse_skill_md

logger = logging.getLogger(__name__)

SKILL_GENE_PREFIX: Final = "gene_distilled_s2g-"


def _repo_assets_skills() -> Path:
    return Path(__file__).resolve().parent.parent / "assets" / "skills"


def skill_roots() -> list[tuple[str, Path]]:
    """Ordered (level, root) pairs, highest priority first."""
    from evolver.config import SKILL_ROOTS_OVERRIDE
    from evolver.gep.paths import get_workspace_root

    override = SKILL_ROOTS_OVERRIDE.strip()
    if override:
        return [
            ("override", Path(part).expanduser()) for part in override.split(":") if part.strip()
        ]

    workspace = get_workspace_root()
    home = Path.home()
    roots: list[tuple[str, Path]] = [
        ("project", workspace / ".agents" / "skills"),
        ("project", workspace / ".claude" / "skills"),
        ("user", home / ".agents" / "skills"),
        ("user", home / ".zcode" / "skills"),
        ("user", home / ".claude" / "skills"),
        ("builtin", _repo_assets_skills()),
    ]
    return roots


def _skill_name_for(md_path: Path, text: str) -> str:
    parsed = parse_skill_md(text)
    return parsed.name or md_path.parent.name


def discover_skills() -> list[dict[str, Any]]:
    """Walk the skill roots in priority order; shadow same-name lower levels."""
    seen: set[str] = set()
    found: list[dict[str, Any]] = []
    for level, root in skill_roots():
        if not root.is_dir():
            continue
        candidates = sorted(p for p in root.iterdir() if p.is_dir())
        flat = root / "SKILL.md"
        if flat.is_file():
            candidates = [root, *candidates]
        for skill_dir in candidates:
            md = skill_dir / "SKILL.md"
            if not md.is_file():
                continue
            try:
                text = md.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.debug("[SkillAssets] unreadable %s: %s", md, exc)
                continue
            if not text.strip():
                continue
            name = _skill_name_for(md, text)
            key = name.casefold()
            if key in seen:
                continue  # shadowed by a higher-priority root (EvoX model)
            seen.add(key)
            found.append(
                {
                    "name": name,
                    "level": level,
                    "path": str(md),
                    "root": str(root),
                }
            )
    return found


def sync_skills(dry_run: bool = False) -> dict[str, Any]:
    """Convert discovered skills to genes and install them into the store."""
    from evolver.gep.asset_store import upsert_gene
    from evolver.gep.skill2gep import skill_to_gene_dict

    installed: list[dict[str, Any]] = []
    errors: list[str] = []
    for skill in discover_skills():
        gene = skill_to_gene_dict(skill["path"])
        if gene is None:
            errors.append(f"{skill['name']}: conversion failed")
            continue
        if dry_run:
            installed.append(
                {
                    "id": gene["id"],
                    "name": skill["name"],
                    "level": skill["level"],
                    "action": "would_install",
                }
            )
            continue
        try:
            # skill2gep's local hash differs from the store's canonical
            # formula — recompute or load_genes' verification silently
            # drops the entry (content-hash mismatch).
            from evolver.gep.content_hash import compute_asset_id

            gene["asset_id"] = compute_asset_id(gene)
            upsert_gene(gene)
            installed.append({"id": gene["id"], "name": skill["name"], "level": skill["level"]})
        except Exception as exc:  # store failures must not abort the batch
            errors.append(f"{skill['name']}: {exc}")
    return {
        "ok": not errors,
        "discovered": len(installed) + len(errors),
        "installed": installed,
        "errors": errors,
        "dry_run": dry_run,
        "next_action": "swarm_tick",
    }


def list_skill_genes() -> list[dict[str, Any]]:
    """Skill-derived genes currently in the store (provenance view)."""
    from evolver.gep.asset_store import load_genes

    out: list[dict[str, Any]] = []
    for gene in load_genes():
        gid = str(gene.get("id") or "")
        if gid.startswith(SKILL_GENE_PREFIX):
            source = gene.get("_source") or {}
            out.append(
                {
                    "id": gid,
                    "skill_name": source.get("skill_name") or gid.removeprefix(SKILL_GENE_PREFIX),
                    "summary": gene.get("summary", ""),
                    "signals_match": gene.get("signals_match", []),
                    "category": gene.get("category"),
                }
            )
    return out


__all__ = [
    "SKILL_GENE_PREFIX",
    "discover_skills",
    "list_skill_genes",
    "skill_roots",
    "sync_skills",
]
