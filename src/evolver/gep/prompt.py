"""LLM prompt assembly for evolution cycles — utility-aware SNR packer (算子即基因 P1-4).

Replaces blind 24,000-char tail slicing with whole-section utility-density
packing (`utility / token_cost`) targeting a high-SNR `< 4,000 tokens` budget:
- Mandatory pinned sections (`Charter`, `Schemas`, `CONSTITUTIONAL ETHICS`,
  `Cycle Metadata`, `Context [Execution]`, `## Previous Episode` when present,
  `## Evidence Pack` when present, `## Host Clues` when present,
  `## Selected Gene`, `## Task`) are always preserved intact in exact canonical
  order.
- Optional auxiliary previews (`Wiki Impact`, `Gene Preview`, `Capsule Preview`,
  `Capability Candidates`, `Recent History`, `Failed Capsules`,
  `External Candidates`, `Hub Matched`, `Hub Lessons`) are ranked by signal-aware
  utility density and packed whole when they fit, or cleanly omitted with an
  explicit summary comment — never slicing JSON blocks or trailing instructions
  in half.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from evolver.gep.schemas.protocol import (
    VALID_CATEGORIES,
    VALID_OUTCOME_STATUSES,
    VALID_RISK_LEVELS,
    VALID_TRACE_STAGES,
    render_enum,
    render_enum_list,
)

#: High-SNR default prompt token budget (< 4,000 tokens, ~4 chars/token).
PROMPT_TOKEN_BUDGET: Final[int] = 3_800
PROMPT_DEFAULT_MAX_CHARS: Final[int] = PROMPT_TOKEN_BUDGET * 4

#: Short standing rule. Mechanical gates carry the rest, at the moment they fire.
CHARTER_PREAMBLE: Final = (
    "Before mutating, state one falsifiable hypothesis and the expected check change; "
    "after verification, compare the engine-recorded outcome against your expectation. "
    "Prefer the simplest minimal diff consistent with Previous Episode and Evidence Pack. "
    "When a gate rejects or truncates output, use episode_inspect to examine raw evidence "
    "rather than guessing. Record durable laws in genes and lessons; keep current-session "
    "scratch in WORKING_SESSION.md."
)

_PREVIEW_STRIP_FIELDS = {
    "diff",
    "compact_diff",
    "execution_trace",
    "learning_history",
    "anti_patterns",
    "evolution_history",
    "content",
}

_EMPTY_PLACEHOLDERS: Final[frozenset[str]] = frozenset({"", "(none)", "[]", "{}"})


@dataclass(frozen=True)
class PromptSection:
    """One discrete section candidate for utility-density prompt assembly."""

    name: str
    text: str
    utility: float = 1.0
    pinned: bool = False


def estimate_tokens(text: str) -> int:
    """Deterministic conservative token estimate (~4 UTF-8 chars per token)."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _strip_bloat(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_bloat(v) for k, v in obj.items() if k not in _PREVIEW_STRIP_FIELDS}
    if isinstance(obj, list):
        return [_strip_bloat(v) for v in obj]
    return obj


def compact_preview_for_prompt(preview: str) -> str:
    """Strip bloated fields from a markdown-fenced JSON preview."""
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


def _wiki_impact_block(limit: int = 12, chars: int = 1500) -> str:
    """S27: rejected-mutation memory headings."""
    try:
        from evolver.gep.wiki import wiki_dir

        text = (wiki_dir() / "skill-impact.md").read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    headings = [ln.lstrip("# ").strip() for ln in text.splitlines() if ln.startswith("## ")]
    if not headings:
        return ""
    recent = list(reversed(headings[-limit:]))
    block = "\n".join(
        [
            "## Wiki Impact — REJECTED mutations (do NOT repeat these approaches)",
            "",
        ]
        + [f"- {h}" for h in recent]
    )
    return block[:chars]


def _bound_context_body(context: str, max_context_chars: int) -> str:
    raw = context or "(none)"
    if len(raw) <= max_context_chars:
        return raw
    lines = raw.splitlines()
    if len(lines) <= 8:
        half = max(64, (max_context_chars - 60) // 2)
        omitted_chars = len(raw) - 2 * half
        return (
            f"{raw[:half]}\n... (+{omitted_chars} context chars omitted for SNR) ...\n{raw[-half:]}"
        )
    kept_head: list[str] = []
    kept_tail: list[str] = []
    half_budget = max(80, (max_context_chars - 80) // 2)
    used = 0
    for ln in lines:
        if used + len(ln) + 1 > half_budget:
            break
        kept_head.append(ln)
        used += len(ln) + 1
    used = 0
    for ln in reversed(lines[len(kept_head) :]):
        if used + len(ln) + 1 > half_budget:
            break
        kept_tail.append(ln)
        used += len(ln) + 1
    kept_tail.reverse()
    omitted_lines = max(1, len(lines) - len(kept_head) - len(kept_tail))
    return "\n".join(
        [
            *kept_head,
            f"... (+{omitted_lines} context lines omitted for <4000-token SNR budget) ...",
            *kept_tail,
        ]
    )


def _signal_relevance_boost(body: str, signals: Sequence[str]) -> float:
    if not body or body.strip() in _EMPTY_PLACEHOLDERS or not signals:
        return 0.0
    lowered = body.lower()
    hits = 0
    for sig in signals:
        head = str(sig or "").split(":", 1)[0].strip().lower()
        if head and len(head) >= 3 and head in lowered:
            hits += 1
    return min(2.0, hits * 0.6)


def _optional_section(
    heading: str,
    body: str,
    *,
    base_utility: float,
    signals: Sequence[str],
) -> PromptSection:
    clean = body.strip()
    is_empty = clean in _EMPTY_PLACEHOLDERS
    effective_utility = (
        0.05 if is_empty else (base_utility + _signal_relevance_boost(clean, signals))
    )
    rendered = f"## {heading}\n{body}\n"
    return PromptSection(
        name=heading,
        text=rendered,
        utility=effective_utility,
        pinned=False,
    )


def pack_prompt_sections(
    sections: Sequence[PromptSection],
    *,
    max_tokens: int = PROMPT_TOKEN_BUDGET,
) -> tuple[str, list[str]]:
    """Pack *sections* by `utility / token_cost` density without mid-section truncation.

    Pinned sections are always included in canonical order. Optional sections are
    greedily selected by descending utility density while total estimated tokens
    remain within *max_tokens*, then re-emitted in their original declaration order.
    """
    active = [s for s in sections if s.text]
    pinned_indices = {idx for idx, s in enumerate(active) if s.pinned}
    used_tokens = sum(estimate_tokens(active[idx].text) for idx in pinned_indices)

    candidates: list[tuple[float, int, int]] = []
    for idx, sec in enumerate(active):
        if idx in pinned_indices:
            continue
        cost = max(1, estimate_tokens(sec.text))
        # Density = utility / token_cost (scaled gently so high-utility substantive blocks win)
        density = sec.utility / max(12, cost)
        candidates.append((density, -idx, idx))

    candidates.sort(reverse=True)
    chosen_indices = set(pinned_indices)
    omitted_names: list[str] = []

    for _density, _neg_idx, idx in candidates:
        sec = active[idx]
        cost = estimate_tokens(sec.text)
        if used_tokens + cost <= max_tokens:
            chosen_indices.add(idx)
            used_tokens += cost
        else:
            omitted_names.append(sec.name)

    # Preserve original declaration order for omitted summary readability too
    omitted_set = set(omitted_names)
    ordered_omitted = [s.name for s in active if s.name in omitted_set]

    out_chunks: list[str] = []
    summary_inserted = False
    last_idx = len(active) - 1
    for idx, sec in enumerate(active):
        if idx == last_idx and ordered_omitted and not summary_inserted and sec.name == "Task":
            omitted_csv = ", ".join(ordered_omitted)
            out_chunks.append(
                f"<!-- prompt_packer: omitted {len(ordered_omitted)} low-utility section(s) "
                f"to stay within {max_tokens}-token SNR budget: {omitted_csv} -->\n"
            )
            summary_inserted = True
        if idx in chosen_indices:
            out_chunks.append(sec.text)

    if ordered_omitted and not summary_inserted:
        omitted_csv = ", ".join(ordered_omitted)
        out_chunks.append(
            f"<!-- prompt_packer: omitted {len(ordered_omitted)} low-utility section(s) "
            f"to stay within {max_tokens}-token SNR budget: {omitted_csv} -->\n"
        )

    return "\n".join(out_chunks), ordered_omitted


def build_gep_prompt(
    *,
    now_iso: str,
    context: str,
    signals: list[str],
    selector: dict[str, Any] | None,
    parent_event_id: str | None,
    selected_gene: dict[str, Any] | None,
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
    strategy_policy: dict[str, Any] | None,
    initial_user_prompt: str | None,
    evidence_pack: str = "",
    episode_block: str = "",
    clue_block: str = "",
    max_chars: int = PROMPT_DEFAULT_MAX_CHARS,
) -> str:
    _ = (capsule_candidates, initial_user_prompt)
    genes_preview = _compact_or_passthrough(genes_preview)
    capsules_preview = _compact_or_passthrough(capsules_preview)

    selected_gene_block = ""
    if selected_gene:
        selected_gene_block = (
            f"Selected Gene: {selected_gene.get('id', 'unknown')}\n"
            f"Category: {selected_gene.get('category', 'unknown')}\n"
            f"Summary: {selected_gene.get('summary', '')}\n"
            f"Strategy: {json.dumps(selected_gene.get('strategy', []), ensure_ascii=False)}"
        )

    cat_enum = render_enum(VALID_CATEGORIES)
    risk_enum = render_enum(VALID_RISK_LEVELS)
    outcome_enum = render_enum(VALID_OUTCOME_STATUSES)
    trace_enum = render_enum_list(VALID_TRACE_STAGES)

    effective_max_chars = max(2_400, int(max_chars))
    token_budget = max(600, effective_max_chars // 4)
    bounded_context = _bound_context_body(context, max(600, effective_max_chars // 4))

    header_lines = [
        "# GENOME EVOLUTION PROTOCOL (GEP) v1.8.0",
        "",
        "You are participating in the Genome Evolution Protocol.",
        "Your output MUST be one valid JSON object conforming to the schemas below.",
        "",
        "## Charter",
        CHARTER_PREAMBLE,
        "",
        "## Schemas",
        "",
        (
            f"- Mutation: {{ type: 'Mutation', id, category: \"{cat_enum}\", "
            f'trigger_signals, target, expected_effect, risk_level: "{risk_enum}" }}'
        ),
        "- PersonalityState: { rigor, creativity, risk_tolerance } in [0,1]",
        (
            "- EvolutionEvent: { type: 'EvolutionEvent', id, run_id, timestamp, "
            f'gene_id, signals, outcome: {{ status: "{outcome_enum}", score }} }}'
        ),
        (
            f"- Gene: {{ type: 'Gene', id, category: \"{cat_enum}\", "
            "signals_match, strategy, validation, constraints }"
        ),
        (
            "- Capsule: { type: 'Capsule', id, trigger, gene, summary, confidence, "
            f'outcome: {{ status: "{outcome_enum}", score }}, '
            f"execution_trace: [{{ step, stage: {{{trace_enum}}}, cmd, exit }}] }}"
        ),
        "",
        "## CONSTITUTIONAL ETHICS",
        "",
        "1. HUMAN WELFARE: Never produce content that harms humans.",
        "2. TRUTHFULNESS: Do not fabricate files, tests, or results.",
        "3. TRANSPARENCY: Report uncertainty explicitly.",
        "4. AUTONOMY: Respect user intent; ask for clarification on ambiguous risky requests.",
        "",
        "## Cycle Metadata",
        f"- cycle_id: {cycle_id}",
        f"- timestamp: {now_iso}",
        f"- parent_event_id: {parent_event_id or 'null'}",
        f"- signals: {json.dumps(signals, ensure_ascii=False)}",
        f"- selector: {json.dumps(selector or {}, ensure_ascii=False)}",
        f"- strategy_policy: {json.dumps(strategy_policy or {}, ensure_ascii=False)}",
        "",
        "## Context [Execution]",
        bounded_context,
        "",
    ]

    wiki_block = _wiki_impact_block()
    failed_caps_str = json.dumps(failed_capsules, ensure_ascii=False) if failed_capsules else "[]"
    hub_lessons_str = json.dumps(hub_lessons, ensure_ascii=False) if hub_lessons else "[]"

    sections: list[PromptSection] = [
        PromptSection(name="Core Header", text="\n".join(header_lines), pinned=True),
    ]
    # 经验即证据 §5.2 canonical order:
    # Previous Episode -> Evidence Pack -> Host Clues -> Selected Gene
    if episode_block:
        sections.append(
            PromptSection(name="Previous Episode", text=f"{episode_block}\n", pinned=True)
        )
    if evidence_pack:
        sections.append(PromptSection(name="Evidence Pack", text=f"{evidence_pack}\n", pinned=True))
    if clue_block:
        sections.append(PromptSection(name="Host Clues", text=f"{clue_block}\n", pinned=True))

    sections.append(
        PromptSection(
            name="Selected Gene",
            text=f"## Selected Gene\n{selected_gene_block or '(none)'}\n",
            pinned=True,
        )
    )

    if wiki_block:
        sections.append(
            PromptSection(
                name="Wiki Impact",
                text=f"{wiki_block}\n",
                utility=4.2 + _signal_relevance_boost(wiki_block, signals),
                pinned=False,
            )
        )

    sections.extend(
        [
            _optional_section(
                "Gene Preview",
                genes_preview or "[]",
                base_utility=3.2,
                signals=signals,
            ),
            _optional_section(
                "Capsule Preview",
                capsules_preview or "[]",
                base_utility=2.6,
                signals=signals,
            ),
            _optional_section(
                "Recent History",
                recent_history or "(none)",
                base_utility=2.8,
                signals=signals,
            ),
            _optional_section(
                "Failed Capsules",
                failed_caps_str,
                base_utility=3.0,
                signals=signals,
            ),
            _optional_section(
                "Capability Candidates",
                capability_candidates_preview or "(none)",
                base_utility=1.8,
                signals=signals,
            ),
            _optional_section(
                "External Candidates",
                external_candidates_preview or "(none)",
                base_utility=1.4,
                signals=signals,
            ),
            _optional_section(
                "Hub Matched",
                hub_matched_block or "(none)",
                base_utility=1.6,
                signals=signals,
            ),
            _optional_section(
                "Hub Lessons",
                hub_lessons_str,
                base_utility=1.5,
                signals=signals,
            ),
            PromptSection(
                name="Task",
                text=(
                    "## Task\n"
                    "Produce a GEP-compliant Mutation or EvolutionEvent JSON. "
                    "Do NOT include prose outside the JSON."
                ),
                pinned=True,
            ),
        ]
    )

    packed, _omitted = pack_prompt_sections(sections, max_tokens=token_budget)
    return packed


__internals = {
    "compactPreviewForPrompt": compact_preview_for_prompt,
    "PREVIEW_STRIP_FIELDS": _PREVIEW_STRIP_FIELDS,
}


def build_inplace_gep_prompt(
    *,
    signals: list[str] | None = None,
    selected_gene: dict[str, Any] | None = None,
    now_iso: str | None = None,
    parent_event_id: str | None = None,
    cycle_id: str | None = None,
) -> str:
    """Build a constrained prompt for ``execution_mode=inplace`` genes."""
    from evolver.gep.selector import INPLACE_BLAST_MAX_FILES, INPLACE_BLAST_MAX_LINES

    gene = selected_gene or {}
    gene_id = gene.get("id", "unknown")
    strategy = gene.get("strategy")
    if isinstance(strategy, list) and strategy:
        strategy_text = "; ".join(str(s) for s in strategy)
    elif strategy:
        strategy_text = str(strategy)
    else:
        strategy_text = "Identify parameter values to tune; avoid structural rewrites."

    sigs = [str(s) for s in (signals or [])]
    lines = [
        "# IN-PLACE MODE (PARAMETER-ONLY)",
        "",
        CHARTER_PREAMBLE,
        "",
        "You are operating in **IN-PLACE MODE**.",
        "Apply **PARAMETER-ONLY** changes — no architecture rewrites, no new modules.",
        f"Blast radius hard cap: **max {INPLACE_BLAST_MAX_FILES} files**, "
        f"**max {INPLACE_BLAST_MAX_LINES} lines** total.",
        "",
        f"Cycle: {cycle_id or 'n/a'}",
        f"Now: {now_iso or ''}",
        f"Parent event: {parent_event_id or 'n/a'}",
        f"Selected gene: `{gene_id}`",
        f"Signals: {', '.join(sigs) if sigs else '(none)'}",
        f"Strategy: {strategy_text}",
        "",
        "Constraints:",
        f"- Touch at most {INPLACE_BLAST_MAX_FILES} files",
        f"- Change at most {INPLACE_BLAST_MAX_LINES} lines",
        "- Prefer constants, timeouts, thresholds, and config keys",
        "- Do not introduce new dependencies",
    ]
    return "\n".join(lines)


__all__ = [
    "CHARTER_PREAMBLE",
    "PROMPT_DEFAULT_MAX_CHARS",
    "PROMPT_TOKEN_BUDGET",
    "PromptSection",
    "__internals",
    "build_gep_prompt",
    "build_inplace_gep_prompt",
    "compact_preview_for_prompt",
    "estimate_tokens",
    "pack_prompt_sections",
]
