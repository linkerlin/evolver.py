"""Skill → GEP gene converter — turn agent skills into evolvable genes.

Equivalent to Node's ``evolver/src/gep/skill2gep.js``.

Skills are reusable capabilities stored in ``SKILL.md`` files.
This module converts a skill's content into a *gene* that the GEP
selector can use:

1. Parse the skill Markdown.
2. Extract intent, trigger phrases, and core heuristics.
3. Build a gene dict with a high signal-match score for the
   skill's domain.

Design notes
------------
* Stateless — reads skill files at call time.
* Signal keywords are derived from the skill filename + headers.
* Genes are plain dicts compatible with :mod:`selector` and
  :mod:`epigenetics`.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evolver.gep.epigenetics import boost_gene
from evolver.gep.paths import get_workspace_root

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SkillGene:
    gene_id: str
    name: str
    intent: str
    trigger_phrases: list[str]
    signal_keywords: list[str]
    source_path: str
    confidence: float = 0.8
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_gene_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for :mod:`selector`."""
        return {
            "gene_id": self.gene_id,
            "name": self.name,
            "intent": self.intent,
            "trigger_phrases": self.trigger_phrases,
            "signal_keywords": self.signal_keywords,
            "source_path": self.source_path,
            "confidence": self.confidence,
            "metadata": self.metadata,
            "epigenetic_marks": [],
        }


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _extract_headers(text: str) -> list[str]:
    """Extract Markdown H1/H2 headers."""
    return re.findall(r"^#{1,2}\s+(.+)$", text, re.MULTILINE)


def _extract_trigger_phrases(text: str) -> list[str]:
    """Look for explicit trigger phrases in skill text.

    Matches lines like:
    * Trigger: "do X"
    * trigger: do X
    - Trigger: do X
    """
    phrases: list[str] = []
    for line in text.splitlines():
        m = re.search(r'(?:^|\s)[Tt]rigger[s]?:\s*["\']?(.+?)["\']?(?:\s*$)', line)
        if m:
            phrases.append(m.group(1).strip())
    return phrases


def _build_signal_keywords(name: str, headers: list[str]) -> list[str]:
    """Build signal keywords from skill name and headers."""
    keywords: set[str] = set()
    # Name tokens
    keywords.update(name.lower().replace("_", " ").replace("-", " ").split())
    # Header tokens
    for h in headers:
        words = re.findall(r"[a-zA-Z]{3,}", h.lower())
        keywords.update(words)
    return sorted(keywords)


def _build_intent(text: str) -> str:
    """Extract the first non-heading paragraph as intent description."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    for para in paragraphs:
        # Skip pure Markdown headings
        if para.startswith("#"):
            continue
        # Truncate to first sentence or 200 chars
        sentence = para.split(".")[0] + "."
        return sentence[:200]
    return "No intent extracted."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def skill_to_gene(path: Path | str) -> SkillGene | None:
    """Convert a single skill file into a :class:`SkillGene`.

    Returns ``None`` if the file cannot be read or is empty.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("[Skill2GEP] Failed to read %s: %s", p, exc)
        return None

    if not text.strip():
        return None

    name = p.stem
    headers = _extract_headers(text)
    triggers = _extract_trigger_phrases(text)
    keywords = _build_signal_keywords(name, headers)
    intent = _build_intent(text)

    gene_id = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    gene = SkillGene(
        gene_id=gene_id,
        name=name,
        intent=intent,
        trigger_phrases=triggers,
        signal_keywords=keywords,
        source_path=str(p.resolve()),
        confidence=0.8,
    )
    # Boost the gene slightly so skills are preferred over generic genes
    boost_gene(gene.to_gene_dict(), amount=0.5)
    return gene


def scan_skills(
    *,
    root: Path | None = None,
    glob: str = "**/*.md",
) -> list[SkillGene]:
    """Scan the workspace for skill files and convert each to a gene.

    Default *glob* is ``"**/*.md"`` — you may want to narrow it to
    ``"**/*SKILL.md"`` or ``".agents/skills/**/*.md"``.
    """
    cwd = root or get_workspace_root()
    genes: list[SkillGene] = []
    for md_file in cwd.rglob(glob):
        gene = skill_to_gene(md_file)
        if gene is not None:
            genes.append(gene)
    logger.info("[Skill2GEP] Scanned %d skill file(s)", len(genes))
    return genes


def skill_genes_to_selector_pool(genes: list[SkillGene]) -> list[dict[str, Any]]:
    """Convert a list of :class:`SkillGene` to the plain-dict pool used by
    :mod:`selector`.
    """
    return [g.to_gene_dict() for g in genes]
