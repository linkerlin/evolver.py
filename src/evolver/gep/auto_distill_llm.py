"""LLM response distiller — extract structured knowledge from raw LLM output.

Equivalent to Node's ``evolver/src/gep/autoDistillLLM.js``.

Takes a raw LLM response (text, JSON, or Markdown) and extracts
structured *knowledge atoms*: facts, rules, code patterns, and
design decisions. Outputs are written to the memory graph as
``llm_distill`` events so that :mod:`recall_inject` can match them.

Design notes
------------
* Stateless — all inputs are passed as arguments.
* Uses simple heuristics (regex / string parsing) so it works offline.
* For richer extraction an actual LLM call could be added behind a
  feature flag, but the offline path is the default.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evolver.gep.memory_graph import get_memory_graph_path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class LLMDistillResult:
    facts: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_event(self, source: str = "") -> dict[str, Any]:
        return {
            "type": "llm_distill",
            "timestamp": time.time(),
            "source": source,
            "facts": self.facts,
            "rules": self.rules,
            "patterns": self.patterns,
            "decisions": self.decisions,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# Heuristic extractors
# ---------------------------------------------------------------------------


def _extract_facts(text: str) -> list[str]:
    """Extract sentences that look like factual statements."""
    facts: list[str] = []
    # Look for lines starting with "- " or "* " that contain "is" / "are" / "should"
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(("- ", "* ", "• ")):
            content = line[2:].strip()
            if re.search(r"\b(is|are|should|must|can|will)\b", content, re.IGNORECASE):
                facts.append(content)
        # Also catch "Fact:" or "Note:" prefixes
        elif re.match(r"^(Fact|Note|Observation)s?:\s*", line, re.IGNORECASE):
            facts.append(re.sub(r"^(Fact|Note|Observation)s?:\s*", "", line, flags=re.IGNORECASE))
    return facts


def _extract_rules(text: str) -> list[str]:
    """Extract sentences that look like rules or guidelines."""
    rules: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if re.match(r"^(Rule|Guideline|Principle|Heuristic)s?:\s*", line, re.IGNORECASE):
            rules.append(re.sub(r"^(Rule|Guideline|Principle|Heuristic)s?:\s*", "", line, flags=re.IGNORECASE))
        elif re.search(r"\b(never|always|must not|should not|do not|avoid)\b", line, re.IGNORECASE):
            if len(line) > 10:
                rules.append(line)
    return rules


def _extract_patterns(text: str) -> list[str]:
    """Extract code / design patterns."""
    patterns: list[str] = []
    # Look for ``Pattern:`` or code blocks with class/function definitions
    for line in text.splitlines():
        line = line.strip()
        if re.match(r"^(Pattern|Idiom|Anti-pattern)s?:\s*", line, re.IGNORECASE):
            patterns.append(re.sub(r"^(Pattern|Idiom|Anti-pattern)s?:\s*", "", line, flags=re.IGNORECASE))
    # Also extract docstring-like descriptions
    matches = re.findall(r'"""(.{10,200}?)"""', text, re.DOTALL)
    for m in matches:
        patterns.append(m.replace("\n", " ").strip())
    return patterns


def _extract_decisions(text: str) -> list[str]:
    """Extract explicit design decisions."""
    decisions: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if re.match(r"^(Decision|Choice|Trade-off)s?:\s*", line, re.IGNORECASE):
            decisions.append(re.sub(r"^(Decision|Choice|Trade-off)s?:\s*", "", line, flags=re.IGNORECASE))
        elif re.search(r"\b(decided to|chose to|opted for|prefer)\b", line, re.IGNORECASE):
            if len(line) > 10:
                decisions.append(line)
    return decisions


def _compute_confidence(result: LLMDistillResult) -> float:
    """Simple confidence based on extraction richness."""
    total = len(result.facts) + len(result.rules) + len(result.patterns) + len(result.decisions)
    return min(1.0, total / 20.0)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def distill_llm_response(
    text: str,
    *,
    source: str = "",
) -> LLMDistillResult:
    """Distill structured knowledge from a raw LLM response *text*."""
    result = LLMDistillResult(
        facts=_extract_facts(text),
        rules=_extract_rules(text),
        patterns=_extract_patterns(text),
        decisions=_extract_decisions(text),
    )
    result.confidence = _compute_confidence(result)
    return result


def distill_and_append(
    text: str,
    *,
    source: str = "",
    path: Path | None = None,
) -> LLMDistillResult:
    """Distill *text* and append the result to the memory graph."""
    result = distill_llm_response(text, source=source)
    p = path or get_memory_graph_path()
    event = result.to_event(source=source)
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        logger.info(
            "[AutoDistillLLM] Appended distill (facts=%d, rules=%d, patterns=%d, decisions=%d)",
            len(result.facts),
            len(result.rules),
            len(result.patterns),
            len(result.decisions),
        )
    except OSError as exc:
        logger.warning("[AutoDistillLLM] Failed to append distill event: %s", exc)
    return result
