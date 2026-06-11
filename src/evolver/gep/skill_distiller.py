"""Skill distiller — extract reusable skills from conversation / code.

Equivalent to Node's ``evolver/src/gep/skillDistiller.js``.

Takes a raw input (conversation transcript, PR description, or code
review) and attempts to extract a reusable *skill*: a compact,
structured piece of knowledge that can be saved as a Markdown file
and later reused via :mod:`skill2gep`.

Distillation pipeline
---------------------
1. **Chunk** — split input into logical sections.
2. **Identify** — detect patterns, rules, or heuristics.
3. **Generalise** — remove project-specific names, keep principles.
4. **Package** — format as Markdown with trigger phrases.
5. **Write** — save to ``evolver/skills/<name>.md``.

Design notes
------------
* Offline — no LLM calls by default.
* Output is human-readable Markdown.
* Duplicate detection prevents overwriting existing skills.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evolver.gep.paths import get_workspace_root

logger = logging.getLogger(__name__)

# Default output directory for distilled skills
DEFAULT_SKILL_DIR = Path("evolver") / "skills"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class DistilledSkill:
    name: str
    intent: str
    triggers: list[str]
    heuristics: list[str]
    examples: list[str]
    source_hash: str

    def to_markdown(self) -> str:
        lines = [
            f"# {self.name}",
            "",
            f"> {self.intent}",
            "",
            "## Triggers",
            "",
        ]
        for t in self.triggers:
            lines.append(f"- {t}")
        lines.extend(["", "## Heuristics", ""])
        for h in self.heuristics:
            lines.append(f"- {h}")
        if self.examples:
            lines.extend(["", "## Examples", ""])
            for e in self.examples:
                lines.append(f"```\n{e}\n```")
        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Heuristic extraction
# ---------------------------------------------------------------------------


def _chunk_text(text: str, max_lines: int = 50) -> list[str]:
    """Split *text* into chunks of at most *max_lines* lines."""
    lines = text.splitlines()
    chunks: list[str] = []
    for i in range(0, len(lines), max_lines):
        chunks.append("\n".join(lines[i : i + max_lines]))
    return chunks


def _extract_rules(text: str) -> list[str]:
    """Extract imperative sentences that look like rules."""
    rules: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(("- ", "* ", "• ")):
            content = line[2:].strip()
            if re.search(r"\b(should|must|never|always|avoid|prefer|use)\b", content, re.IGNORECASE):
                rules.append(content)
        elif re.search(r"\b(should|must|never|always|avoid|prefer|use)\b", line, re.IGNORECASE):
            if len(line) > 10 and len(line) < 300:
                rules.append(line)
    return rules


def _extract_triggers(text: str) -> list[str]:
    """Extract phrases that look like user requests."""
    triggers: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        # Match "how do I...", "can you...", "please..."
        m = re.search(r'^(?:how\s+(?:do|can|should)\s+i|can\s+you|please)\s+(.+)[?.]?$', line, re.IGNORECASE)
        if m:
            triggers.append(m.group(1).strip())
    return triggers


def _generalise(text: str) -> str:
    """Remove project-specific identifiers to make text reusable."""
    # Replace repo-specific paths
    text = re.sub(r"[A-Za-z0-9_-]+/[A-Za-z0-9_/-]+\.[a-z]+", "<file>", text)
    # Replace specific function names (camelCase or snake_case)
    text = re.sub(r"\b[a-z][a-zA-Z0-9_]{3,}\b", "<func>", text)
    # Replace numbers
    text = re.sub(r"\b\d+\b", "<n>", text)
    return text


def _build_intent(rules: list[str]) -> str:
    """Build a one-sentence intent from the first rule."""
    if rules:
        first = rules[0]
        # Capitalise first letter, ensure period
        intent = first[0].upper() + first[1:]
        if not intent.endswith("."):
            intent += "."
        return intent
    return "Generalised skill extracted from conversation."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def distill_skill(
    text: str,
    *,
    name: str | None = None,
) -> DistilledSkill | None:
    """Distil a reusable skill from *text*.

    Returns ``None`` if no heuristics could be extracted.
    """
    chunks = _chunk_text(text)
    all_rules: list[str] = []
    all_triggers: list[str] = []
    for chunk in chunks:
        all_rules.extend(_extract_rules(chunk))
        all_triggers.extend(_extract_triggers(chunk))

    if not all_rules and not all_triggers:
        return None

    # Deduplicate
    rules = sorted(set(all_rules))
    triggers = sorted(set(all_triggers))
    examples = [_generalise(rules[0])] if rules else []

    source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    skill_name = name or f"skill_{source_hash}"

    return DistilledSkill(
        name=skill_name,
        intent=_build_intent(rules),
        triggers=triggers,
        heuristics=rules,
        examples=examples,
        source_hash=source_hash,
    )


def save_skill(
    skill: DistilledSkill,
    *,
    output_dir: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Save *skill* as a Markdown file.

    Returns the written path.
    """
    root = get_workspace_root()
    out = (output_dir or (root / DEFAULT_SKILL_DIR)).resolve()
    out.mkdir(parents=True, exist_ok=True)

    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", skill.name)
    path = out / f"{safe_name}.md"

    if path.exists() and not overwrite:
        logger.info("[SkillDistiller] Skill already exists: %s", path)
        return path

    content = skill.to_markdown()
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    tmp.replace(path)
    logger.info("[SkillDistiller] Saved skill to %s", path)
    return path


def distill_and_save(
    text: str,
    *,
    name: str | None = None,
    output_dir: Path | None = None,
) -> Path | None:
    """Distil *text* and save the resulting skill.

    Returns the path, or ``None`` if nothing could be distilled.
    """
    skill = distill_skill(text, name=name)
    if skill is None:
        return None
    return save_skill(skill, output_dir=output_dir)
