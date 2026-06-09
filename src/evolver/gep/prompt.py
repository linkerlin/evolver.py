"""LLM prompt assembly for evolution cycles.

Equivalent to evolver/src/gep/prompt.js (obfuscated).
"""

from __future__ import annotations

import json
import re
from typing import Any

from evolver.config import PROMPT_MAX_CHARS

_PREVIEW_STRIP_FIELDS = {
    "diff",
    "compact_diff",
    "execution_trace",
    "learning_history",
    "anti_patterns",
    "evolution_history",
    "content",
}


def _strip_bloat(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: _strip_bloat(v)
            for k, v in obj.items()
            if k not in _PREVIEW_STRIP_FIELDS
        }
    if isinstance(obj, list):
        return [_strip_bloat(v) for v in obj]
    return obj


def compact_preview_for_prompt(preview: str) -> str:
    """Strip bloated fields from a markdown-fenced JSON preview.

    Handles both raw JSON arrays and ```json\n...\n``` fenced blocks.
    """
    if not isinstance(preview, str):
        return ""
    fence_start = preview.find("```json\n")
    fence_end = preview.rfind("\n```")
    if fence_start != -1 and fence_end != -1 and fence_end > fence_start:
        inner = preview[fence_start + 7 : fence_end]
        suffix = preview[fence_end:]
    else:
        inner = preview
        suffix = ""

    try:
        data = json.loads(inner)
    except json.JSONDecodeError:
        return preview

    stripped = _strip_bloat(data)
    rendered = json.dumps(stripped, indent=2, ensure_ascii=False)
    if fence_start != -1:
        return "```json\n" + rendered + suffix
    return rendered


def _compact_or_passthrough(value: str) -> str:
    if not isinstance(value, str):
        return str(value)
    return compact_preview_for_prompt(value)


def build_gep_prompt(
    *,
    now_iso: str,
    context: str,
    signals: list[str],
    selector: dict[str, Any] | None,
    parent_event_id: str | None,
    selected_gene: dict | None,
    capsule_candidates: str,
    genes_preview: str,
    capsules_preview: str,
    capability_candidates_preview: str,
    external_candidates_preview: str,
    hub_matched_block: str,
    cycle_id: str,
    recent_history: str,
    failed_capsules: list[Any],
    hub_lessons: list[Any],
    strategy_policy: dict | None,
    initial_user_prompt: str | None,
    max_chars: int = PROMPT_MAX_CHARS,
) -> str:
    genes_preview = _compact_or_passthrough(genes_preview)
    capsules_preview = _compact_or_passthrough(capsules_preview)

    selected_gene_block = ""
    if selected_gene:
        selected_gene_block = (
            f"Selected Gene: {selected_gene.get('id', 'unknown')}\n"
            f"Category: {selected_gene.get('category', 'unknown')}\n"
            f"Summary: {selected_gene.get('summary', '')}\n"
            f"Strategy: {json.dumps(selected_gene.get('strategy', []), ensure_ascii=False)}\n"
        )

    lines = [
        "# GENOME EVOLUTION PROTOCOL (GEP) v1.8.0",
        "",
        "You are participating in the Genome Evolution Protocol.",
        "Your output MUST be one valid JSON object conforming to the schemas below.",
        "",
        "## Schemas",
        "",
        "- Mutation: { type: 'Mutation', id, category, trigger_signals, target, expected_effect, risk_level }",
        "- PersonalityState: { rigor, creativity, risk_tolerance } in [0,1]",
        "- EvolutionEvent: { type: 'EvolutionEvent', id, run_id, timestamp, gene_id, signals, outcome }",
        "- Gene: { type: 'Gene', id, category, signals_match, strategy, validation, constraints }",
        "- Capsule: { type: 'Capsule', id, trigger, gene, summary, confidence, outcome }",
        "",
        "## CONSTITUTIONAL ETHICS",
        "",
        "1. HUMAN WELFARE: Never produce content that harms humans.",
        "2. TRUTHFULNESS: Do not fabricate files, tests, or results.",
        "3. TRANSPARENCY: Report uncertainty explicitly.",
        "4. AUTONOMY: Respect user intent; ask for clarification on ambiguous risky requests.",
        "",
        f"## Cycle Metadata",
        f"- cycle_id: {cycle_id}",
        f"- timestamp: {now_iso}",
        f"- parent_event_id: {parent_event_id or 'null'}",
        f"- signals: {json.dumps(signals, ensure_ascii=False)}",
        f"- selector: {json.dumps(selector or {}, ensure_ascii=False)}",
        f"- strategy_policy: {json.dumps(strategy_policy or {}, ensure_ascii=False)}",
        "",
        "## Context [Execution]",
        context or "(none)",
        "",
        "## Selected Gene",
        selected_gene_block or "(none)",
        "",
        "## Gene Preview",
        genes_preview or "[]",
        "",
        "## Capsule Preview",
        capsules_preview or "[]",
        "",
        "## Capability Candidates",
        capability_candidates_preview or "(none)",
        "",
        "## External Candidates",
        external_candidates_preview or "(none)",
        "",
        "## Hub Matched",
        hub_matched_block or "(none)",
        "",
        "## Recent History",
        recent_history or "(none)",
        "",
        "## Failed Capsules",
        json.dumps(failed_capsules, ensure_ascii=False) if failed_capsules else "[]",
        "",
        "## Hub Lessons",
        json.dumps(hub_lessons, ensure_ascii=False) if hub_lessons else "[]",
        "",
        "## Task",
        "Produce a GEP-compliant Mutation or EvolutionEvent JSON. Do NOT include prose outside the JSON.",
    ]
    prompt = "\n".join(lines)

    # Prefix-floor truncation: protect Context [Execution] even under bloat.
    if len(prompt) > max_chars:
        exec_marker = "## Context [Execution]"
        exec_idx = prompt.find(exec_marker)
        if exec_idx != -1:
            prefix = prompt[: exec_idx + len(exec_marker) + 1]
            suffix = prompt[exec_idx + len(exec_marker) + 1 :]
            budget = max_chars - len(prefix) - 100
            if len(suffix) > budget:
                suffix = suffix[:budget] + "\n...[TRUNCATED]...\n"
            prompt = prefix + suffix
        else:
            prompt = prompt[:max_chars] + "\n...[TRUNCATED]...\n"

    return prompt


__internals = {
    "compactPreviewForPrompt": compact_preview_for_prompt,
    "PREVIEW_STRIP_FIELDS": _PREVIEW_STRIP_FIELDS,
}


__all__ = ["build_gep_prompt", "compact_preview_for_prompt", "__internals"]
