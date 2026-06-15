"""Skill → GEP gene converter — turn agent skills into evolvable genes.

Equivalent to ``evolver/src/gep/skill2gep.js`` (714 lines).

Converts a ``SKILL.md`` file into a *gene* dict the GEP selector can use.

Key functions:
  - :func:`parse_skill_md` — parse SKILL.md text into a structured intermediate
    (strategy steps, avoid items, signals, preconditions). Supports English
    **and CJK** section headings. Flat list-item extraction (no folding).
  - :func:`infer_category` — classify a skill as ``repair`` / ``optimize`` /
    ``innovate`` from signals + description, with inflected-form and
    word-boundary matching.
  - :func:`skill_to_gene` — end-to-end conversion: parse → build gene dict
    with ``asset_id``, ``schema_version``, ``routing_hint``, ``_source``
    metadata, and quality heuristics.

Tested by ``test/skill2gepParser.test.js``.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evolver.gep.paths import get_workspace_root

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = "1.6.0"
_STRATEGY_CAP = 28  # compact cap on strategy steps

# ---------------------------------------------------------------------------
# Section keyword tables (English + CJK synonyms)
# ---------------------------------------------------------------------------

#: Map a heading's keyword set to a logical section.
_SECTION_KEYWORDS: dict[str, list[str]] = {
    "workflow": [
        "workflow", "quick workflow", "steps", "process", "procedure",
        "how to use", "usage", "guide",
        # CJK
        "工作流", "快速工作流", "步骤", "流程",
    ],
    "preconditions": [
        "prerequisite", "prerequisites", "preconditions", "requirements",
        "before you start", "setup",
        # CJK
        "前置条件", "前提条件", "触发条件",
    ],
    "avoid": [
        "avoid", "anti-pattern", "anti pattern", "don't", "do not",
        "pitfalls", "common mistakes",
        # CJK
        "不要做", "避免", "注意事项",
    ],
    "output_contract": [
        "output contract", "output gate", "deliverable",
        # CJK
        "输出门", "输出契约",
    ],
    "human_gate": [
        "human gate", "human confirmation", "approval",
        # CJK
        "人工审核", "审批",
    ],
}

#: Signals that trigger repair classification (inflected forms included).
_REPAIR_SIGNALS = [
    "error", "errors", "exception", "failed", "failure", "fail",
    "crash", "crashes", "bug", "bugs", "broken", "fix", "fixed",
    "unstable", "log_error", "test_failure", "recurring_error",
    # CJK
    "错误", "失败", "异常", "修复",
]

#: Signals that trigger innovate classification (word-boundary matched).
_INNOVATE_SIGNALS = [
    "add", "create", "implement", "new feature", "new module",
    "build", "introduce",
    # CJK
    "新增", "创建", "实现",
]

#: Signals that trigger optimize classification.
_OPTIMIZE_SIGNALS = [
    "optimize", "improve", "refactor", "enhance", "upgrade",
    "streamline", "simplify", "performance",
    # CJK
    "优化", "改进", "重构", "升级",
]

#: Safety words that should NOT force repair on an upgrade/optimization skill.
_SAFETY_OVERRIDE_WORDS = {"rollback", "guard", "gate", "versioning", "safe"}


# ---------------------------------------------------------------------------
# Parsed skill dataclass
# ---------------------------------------------------------------------------


@dataclass
class ParsedSkill:
    """Structured intermediate from parsing a SKILL.md."""

    name: str = ""
    description: str = ""
    strategy: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    signals_match: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split YAML frontmatter from body. Returns (metadata_dict, body_text)."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw = match.group(1)
    body = text[match.end() :]
    meta: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip().strip("\"'")
    return meta, body


# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------


def _classify_heading(heading: str) -> str | None:
    """Return the logical section name for a Markdown heading, or None."""
    lower = heading.lower()
    for section, keywords in _SECTION_KEYWORDS.items():
        for kw in keywords:
            if kw in lower or kw in heading:
                return section
    return None


# ---------------------------------------------------------------------------
# List-item extraction (flat — every item is its own step, no folding)
# ---------------------------------------------------------------------------

_LIST_ITEM_RE = re.compile(
    r"^\s*(?:[-*]\s+|\d+\.\s+)(.+)$",  # bullet or numbered
    re.MULTILINE,
)


def _extract_list_items(text: str) -> list[str]:
    """Extract all list items (bullets and numbered) from *text*.

    Flat extraction: every item is independent regardless of indentation.
    Folding was removed in PR #156 after indentation edge cases grew.
    """
    items: list[str] = []
    for match in _LIST_ITEM_RE.finditer(text):
        item = match.group(1).strip()
        if item:
            items.append(item)
    return items


# ---------------------------------------------------------------------------
# Signal extraction (ASCII tokenizer from description)
# ---------------------------------------------------------------------------

_SIGNAL_TOKEN_RE = re.compile(r"[a-z0-9_]{3,}")


def _extract_signals(description: str) -> list[str]:
    """Extract signal keywords from a description string.

    Splits on commas, then tokenizes each segment to ASCII [a-z0-9_]{3,}.
    Pure-CJK segments yield no tokens — a documented limitation.
    """
    signals: list[str] = []
    seen: set[str] = set()
    for segment in description.split(","):
        lower = segment.lower()
        for match in _SIGNAL_TOKEN_RE.finditer(lower):
            token = match.group(0)
            if token not in seen:
                seen.add(token)
                signals.append(token)
    return signals


# ---------------------------------------------------------------------------
# Category inference
# ---------------------------------------------------------------------------


def _word_boundary_match(text: str, word: str) -> bool:
    """Match *word* in *text* at word boundaries (case-insensitive).

    Prevents false positives like "additional" matching "add".
    """
    pattern = r"\b" + re.escape(word) + r"\b"
    return bool(re.search(pattern, text, re.IGNORECASE))


def infer_category(signals: list[str], description: str) -> str:
    """Classify a skill into repair / optimize / innovate.

    Priority: repair > innovate > optimize > default(optimize).

    Safety words (rollback, guard, etc.) do NOT force repair on an
    upgrade/optimization description.
    """
    combined = " ".join(signals) + " " + description
    lower = combined.lower()

    # Check for repair intent (inflected forms + CJK).
    for sig in _REPAIR_SIGNALS:
        if "_" in sig:
            if sig in lower:
                return "repair"
        elif _word_boundary_match(lower, sig):
            return "repair"
        elif sig in lower and len(sig) >= 4:
            # CJK signals are substring-matched.
            return "repair"

    # Check for innovate intent (word-boundary to avoid "additional"→"add").
    for sig in _INNOVATE_SIGNALS:
        if _word_boundary_match(lower, sig):
            return "innovate"

    # Check for optimize intent.
    for sig in _OPTIMIZE_SIGNALS:
        if _word_boundary_match(lower, sig):
            return "optimize"

    return "optimize"  # default


# ---------------------------------------------------------------------------
# parse_skill_md — the core parser
# ---------------------------------------------------------------------------


def parse_skill_md(text: str) -> ParsedSkill:
    """Parse a SKILL.md string into a :class:`ParsedSkill`.

    Supports:
      - YAML frontmatter (name, description).
      - English + CJK section headings.
      - Flat list-item extraction (every item is its own step).
      - Governance-tail preservation (Human Gate, Output Contract).
      - Short preconditions (e.g. "Git", "npm").
      - Strategy cap at :data:`_STRATEGY_CAP`.
    """
    meta, body = _parse_frontmatter(text)
    name = meta.get("name", "")
    description = meta.get("description", "")

    parsed = ParsedSkill(name=name, description=description)

    # Extract signals from the English description.
    parsed.signals_match = _extract_signals(description)

    # Walk the body, tracking the current section.
    current_section: str | None = None
    heading_re = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
    lines = body.split("\n")
    # Build a map of section → accumulated text.
    section_texts: dict[str, list[str]] = {}

    for line in lines:
        h_match = heading_re.match(line)
        if h_match:
            current_section = _classify_heading(h_match.group(2))
            section_texts.setdefault(current_section or "_other", [])
            continue
        if current_section:
            section_texts.setdefault(current_section, []).append(line)
        else:
            section_texts.setdefault("_other", []).append(line)

    # Extract strategy from workflow + output_contract + human_gate sections.
    strategy_items: list[str] = []
    for section in ("workflow", "output_contract", "human_gate"):
        raw = "\n".join(section_texts.get(section, []))
        strategy_items.extend(_extract_list_items(raw))
    # Also include numbered/bulleted items from the body intro if no workflow.
    if not strategy_items:
        raw = "\n".join(section_texts.get("_other", []))
        strategy_items.extend(_extract_list_items(raw))

    parsed.strategy = strategy_items[:_STRATEGY_CAP]

    # Extract avoid items.
    avoid_raw = "\n".join(section_texts.get("avoid", []))
    parsed.avoid = _extract_list_items(avoid_raw)

    # Extract preconditions (keep short ones — no length gate).
    precond_raw = "\n".join(section_texts.get("preconditions", []))
    parsed.preconditions = _extract_list_items(precond_raw)

    return parsed


# ---------------------------------------------------------------------------
# Gene construction
# ---------------------------------------------------------------------------


def _compute_asset_id(gene_dict: dict[str, Any]) -> str:
    """Compute a sha256 content-hash asset_id for a gene."""
    # Hash the canonical JSON (sorted keys, no whitespace) of the gene minus asset_id.
    copy = {k: v for k, v in gene_dict.items() if k != "asset_id"}
    canonical = repr(sorted(copy.items())).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _compute_quality_heuristics(parsed: ParsedSkill) -> dict[str, Any]:
    """Compute quality heuristics for the _source block."""
    return {
        "strategy_steps": len(parsed.strategy),
        "avoid_count": len(parsed.avoid),
        "validation_declared_count": 0,
        "validation_runnable_count": 0,
        "validation_fallback_used": True,
        "signals_extracted": len(parsed.signals_match),
        "preconditions_extracted": len(parsed.preconditions),
    }


def skill_to_gene(path: Path | str) -> SkillGene | None:
    """Convert a single SKILL.md file into a :class:`SkillGene`.

    Returns ``None`` if the file cannot be read or is empty.

    For the full gene dict (with ``asset_id``, ``schema_version``, ``_source``
    metadata), use :func:`skill_to_gene_dict`.
    """
    p = Path(path)
    gene_dict = skill_to_gene_dict(path)
    if gene_dict is None:
        return None

    # Re-parse for backward-compatible intent/trigger extraction.
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    parsed = parse_skill_md(text)

    # Intent: frontmatter description or first body paragraph.
    intent = parsed.description or _extract_first_paragraph(text)

    return SkillGene(
        gene_id=gene_dict.get("id", ""),
        name=gene_dict.get("_source", {}).get("skill_name", p.stem),
        intent=intent,
        trigger_phrases=_extract_trigger_phrases(text),
        signal_keywords=gene_dict.get("signals_match", []),
        source_path=str(p.resolve()),
        confidence=0.8,
        metadata=gene_dict,
    )


def _extract_first_paragraph(text: str) -> str:
    """Extract the first non-heading paragraph as intent description."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    for para in paragraphs:
        if not para.startswith("#"):
            sentence = para.split(".")[0] + "."
            return sentence[:200]
    return ""


def _extract_trigger_phrases(text: str) -> list[str]:
    """Look for explicit trigger phrases in skill text."""
    phrases: list[str] = []
    for line in text.splitlines():
        m = re.search(r'(?:^|\s)[Tt]rigger[s]?:\s*["\']?(.+?)["\']?(?:\s*$)', line)
        if m:
            phrases.append(m.group(1).strip())
    return phrases


def skill_to_gene_dict(path: Path | str) -> dict[str, Any] | None:
    """Convert a single SKILL.md file into a full gene dict.

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

    parsed = parse_skill_md(text)
    category = infer_category(parsed.signals_match, parsed.description)

    skill_name = parsed.name or p.stem
    gene_id = f"gene_distilled_s2g-{skill_name}"

    # Determine skill platform from path if possible (e.g. skills/vercel/env-vars).
    parts = p.parts
    skill_platform = ""
    for i, part in enumerate(parts):
        if part == "skills" and i + 1 < len(parts):
            skill_platform = parts[i + 1]
            break

    gene: dict[str, Any] = {
        "type": "Gene",
        "id": gene_id,
        "summary": (
            parsed.description[:200]
            if parsed.description
            else f"Distilled from skill {skill_name}"
        ),
        "category": category,
        "signals_match": parsed.signals_match[:14],  # compact
        "preconditions": parsed.preconditions or ["Skill has been executed locally"],
        "strategy": parsed.strategy or [
            "Identify the dominant trigger signals from the Skill description.",
            "Apply the smallest targeted change that satisfies the Skill workflow.",
            "Run the Skill validation commands and abort if any fails.",
        ],
        "constraints": {
            "max_files": 12,
            "forbidden_paths": [".git", "node_modules", ".venv"],
        },
        "validation": ["python --version"],
        "avoid": parsed.avoid,
        "schema_version": _SCHEMA_VERSION,
        "epigenetic_marks": [],
        "learning_history": [],
        "anti_patterns": [],
        "routing_hint": None,
        "tool_policy": None,
        "_source": {
            "kind": "skill2gep",
            "skill_name": skill_name,
            "skill_platform": skill_platform,
            "quality_heuristics": _compute_quality_heuristics(parsed),
        },
    }

    gene["asset_id"] = _compute_asset_id(gene)
    return gene


# ---------------------------------------------------------------------------
# Batch scanning
# ---------------------------------------------------------------------------


def scan_skills(
    *,
    root: Path | None = None,
    glob: str = "**/*SKILL.md",
) -> list[SkillGene]:
    """Scan the workspace for SKILL.md files and convert each to a SkillGene."""
    cwd = root or get_workspace_root()
    genes: list[SkillGene] = []
    for md_file in cwd.rglob(glob):
        gene = skill_to_gene(md_file)
        if gene is not None:
            genes.append(gene)
    logger.info("[Skill2GEP] Scanned %d skill file(s)", len(genes))
    return genes


__all__ = [
    "ParsedSkill",
    "SkillGene",
    "infer_category",
    "parse_skill_md",
    "scan_skills",
    "skill_genes_to_selector_pool",
    "skill_to_gene",
]


# ---------------------------------------------------------------------------
# Backward-compatible SkillGene dataclass (wraps the dict-based gene)
# ---------------------------------------------------------------------------


@dataclass
class SkillGene:
    """Legacy dataclass wrapper for a skill-derived gene.

    New code should use :func:`skill_to_gene` (returns a dict) and
    :func:`parse_skill_md` directly. This class is retained for callers
    that depend on attribute access (``.name``, ``.intent``, etc.).
    """

    gene_id: str = ""
    name: str = ""
    intent: str = ""
    trigger_phrases: list[str] = field(default_factory=list)
    signal_keywords: list[str] = field(default_factory=list)
    source_path: str = ""
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


def skill_genes_to_selector_pool(genes: list[SkillGene]) -> list[dict[str, Any]]:
    """Convert a list of :class:`SkillGene` to the plain-dict pool for selector."""
    return [g.to_gene_dict() for g in genes]
