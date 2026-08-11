# ruff: noqa: E501  # generated data module: pprint-wrapped summaries exceed 100 cols
"""Claude context schema routing Gene family (v1.94.0 parity).

Behavioral port of Node ``src/gep/contextRoutingGene.js`` (obfuscated at HEAD;
contract from ``contextSchemaRoutingGene.test.js`` + the bundled seed data).

The family routes context-bloat complaints to specialized compression Genes:
prompt-budget ledger, schema routing dispatcher, tool-schema lazy-load,
skill-manual routing, transcript handoff compression, and memory-index budget.
Asset ids are content-addressed at build time so bundled seed data and the
module output verify identically.
"""

from __future__ import annotations

from typing import Any

from evolver.gep.content_hash import compute_asset_id

FAMILY_GENE_IDS: list[str] = [
    "gene_claude_prompt_budget_ledger",
    "gene_claude_context_schema_routing",
    "gene_claude_tool_schema_lazy_load",
    "gene_claude_skill_manual_routing",
    "gene_claude_transcript_handoff_compression",
    "gene_claude_memory_index_budget",
]

_DISPATCHER_GENE_ID = "gene_claude_context_schema_routing"


# Gene templates (data, mirrors the bundled genes.seed.json entries).
_FAMILY_TEMPLATES: list[dict[str, Any]] = [
    {
        "type": "Gene",
        "category": "optimize",
        "schema_version": "1.8.0",
        "epigenetic_marks": [],
        "learning_history": [],
        "anti_patterns": [],
        "routing_hint": {"tier": "mid", "reasoning_level": "medium"},
        "tool_policy": None,
        "id": "gene_claude_prompt_budget_ledger",
        "signals_match": [
            "prompt_budget_measurement",
            "token_budget_overflow",
            "context_explosion",
            "上下文爆了",
            "token 超限",
            "context budget",
        ],
        "preconditions": [
            "A context-limit failure needs attribution before changing prompts, tools, "
            "memory, or handoff format",
            "At least one local prompt/context source can be measured or estimated independently",
        ],
        "strategy": [
            "Create a budget ledger before editing: fixed system/harness text, user/project "
            "instructions, memory index, recalled memories, tool schemas, MCP instructions, "
            "skill manuals, agent descriptions, and user-pasted payload",
            "Rank sources by marginal savings and risk; prefer lazy-loading low-relevance "
            "tool/manual detail before compressing high-priority policy",
            "Record both absolute tokens and percentage of the total so regressions can be "
            "caught when new tools or skills are added",
            "Attach each compression to a verification target: selected tool still callable, "
            "selected skill still loadable, safety rule still present, or handoff still "
            "sufficient",
            "After changes, re-run the same ledger measurement and report the before/after "
            "delta with any residual irreducible context cost",
        ],
        "validation": [
            "node --test test/contextSchemaRoutingGene.test.js",
            "node scripts/validate-modules.js ./src/gep/signals ./src/gep/contextRoutingGene",
        ],
        "constraints": {"max_files": 8, "forbidden_paths": [".git", "node_modules"]},
        "summary": "Diagnose context explosions with a prompt-budget ledger before deciding whether to "
        "compress tools, skills, memory, policy, or pasted transcripts.",
        "avoid": [
            "guessing the largest source without measuring it",
            "optimizing a small memory index while ignoring much larger always-on tool schemas",
            "reporting a context fix without before/after numbers and a runtime verification "
            "target",
        ],
    },
    {
        "type": "Gene",
        "category": "optimize",
        "schema_version": "1.8.0",
        "epigenetic_marks": [],
        "learning_history": [],
        "anti_patterns": [],
        "routing_hint": {"tier": "mid", "reasoning_level": "medium"},
        "tool_policy": None,
        "id": "gene_claude_context_schema_routing",
        "signals_match": [
            "claude_code_context_bloat",
            "schema_routing_gene_request",
            "蒸馏成基因",
            "Claude Code context",
            "Available agent types",
            "MCP Server Instructions",
        ],
        "preconditions": [
            "Claude Code or another harness injects large tool/MCP/skill instructions "
            "before the user task",
            "The failure mode is prompt/context size or duplicated capability guidance, "
            "while runtime approval gates and parameter validation remain enforced",
        ],
        "strategy": [
            "Classify the bloat source first: user/project policy, memory index, recalled "
            "memory bodies, tool schemas, MCP server instructions, skill descriptions, "
            "agent-type descriptions, or pasted transcript payloads",
            "Route the task to the most specific compression Gene instead of applying one "
            "generic shortening pass; keep this Gene as a compliance-first dispatcher and "
            "decision record",
            "Preserve complete delivery: retain user-preference, approval-gate, validation, "
            "and signature requirements while compressing their wording into stable policy "
            "references",
            "Keep exact tool schemas available through the authorized runtime loader; "
            "routing Genes select a capability family and the runtime loader supplies "
            "authoritative parameters and validation",
            "Validate the routed path by proving the selected Gene appears through selector "
            "or recall injection, the rendered hint stays under the injection ceiling, and "
            "an approved runtime loader can still provide the exact schema when needed",
        ],
        "validation": [
            "node --test test/contextSchemaRoutingGene.test.js test/recallInject.test.js "
            "test/selector.test.js",
            "node scripts/validate-modules.js ./src/gep/assetStore ./src/gep/recallInject "
            "./src/gep/selector ./src/gep/signals ./src/gep/contextRoutingGene "
            "./src/gep/schemas/gene",
            "node scripts/validate-suite.js",
        ],
        "constraints": {"max_files": 8, "forbidden_paths": [".git", "node_modules"]},
        "summary": "Dispatch Claude Code context-bloat work to specialized Genes while retaining "
        "approval gates and requiring exact schemas from authorized runtime loaders.",
        "avoid": [
            "using one broad summary when a narrower tool-schema, skill-manual, memory, or "
            "transcript compression Gene applies",
            "summarizing away exact tool JSON schemas at the moment a real tool call needs "
            "runtime validation",
            "removing user-preference, approval-gate, validation, or signature requirements "
            "merely to save tokens",
            "treating lazy loading as a substitute for the runtime loader and its authoritative "
            "parameter contract",
        ],
    },
    {
        "type": "Gene",
        "category": "optimize",
        "schema_version": "1.8.0",
        "epigenetic_marks": [],
        "learning_history": [],
        "anti_patterns": [],
        "routing_hint": {"tier": "mid", "reasoning_level": "medium"},
        "tool_policy": None,
        "id": "gene_claude_tool_schema_lazy_load",
        "signals_match": [
            "tool_schema_bloat",
            "mcp_tool_schema",
            "lazy_load_schema",
            "工具 schema 太大",
            "tool schema too large",
            "MCP tool schema",
        ],
        "preconditions": [
            "The fixed context includes full tool or MCP JSON schemas before the task "
            "has selected a tool family",
            "The goal is to reduce always-on prompt load without weakening the exact "
            "schema available at call time",
        ],
        "strategy": [
            "Replace always-on full schemas with a compact tool-family card: capability "
            "name, trigger words, risk class, and a pointer to the authoritative schema "
            "loader",
            "Delay expansion of exact parameter schemas until the planner selects that tool "
            "family or the model is about to emit a tool call",
            "Keep schema validation at the tool boundary, not in the compressed prompt; "
            "invalid parameters must still be rejected by the runtime schema",
            "Measure before and after: count always-on schema bytes/tokens, selected schema "
            "bytes/tokens, and total prompt size for a representative task",
            "Regression-test at least one real tool call per lazy-loaded family so the "
            "compression cannot pass by merely hiding unavailable tools",
        ],
        "validation": [
            "node --test test/contextSchemaRoutingGene.test.js test/recallInject.test.js",
            "node scripts/validate-modules.js ./src/gep/signals ./src/gep/recallInject "
            "./src/gep/contextRoutingGene",
        ],
        "constraints": {"max_files": 12, "forbidden_paths": [".git", "node_modules"]},
        "summary": "Shrink always-on tool/MCP schema context by routing through compact tool-family "
        "cards and loading exact JSON schemas just in time.",
        "avoid": [
            "replacing exact schemas with natural-language guesses at call time",
            "dropping enum constraints, required fields, or permission prompts from the runtime "
            "boundary",
            "claiming savings without a before/after token measurement and one real tool-call "
            "regression",
        ],
    },
    {
        "type": "Gene",
        "category": "optimize",
        "schema_version": "1.8.0",
        "epigenetic_marks": [],
        "learning_history": [],
        "anti_patterns": [],
        "routing_hint": {"tier": "mid", "reasoning_level": "medium"},
        "tool_policy": None,
        "id": "gene_claude_skill_manual_routing",
        "signals_match": [
            "skill_list_bloat",
            "skill_manual_bloat",
            "Available agent types",
            "MCP Server Instructions",
            "skill 列表太长",
            "技能列表太长",
        ],
        "preconditions": [
            "The prompt includes many skill descriptions, agent type descriptions, or "
            "MCP server instructions unrelated to the current task",
            "The harness can load a skill or manual after a routing decision is made",
        ],
        "strategy": [
            "Convert each long skill/manual into a short route card containing name, "
            "one-line capability, hard trigger, skip trigger, and safety class",
            "Select at most the relevant skill/manual before loading its full instructions; "
            "do not inject every skill body on every turn",
            "Keep slash-command and user-invocable skill names exact so the router never "
            "invents unavailable skills",
            "Preserve mandatory global policy outside skill manuals when the policy applies "
            "across all tools, but move skill-local details behind the skill loader",
            "Add tests that route a representative Lark/Pencil/Browser/Claude-API task to "
            "the right card while unrelated cards remain compressed",
        ],
        "validation": [
            "node --test test/contextSchemaRoutingGene.test.js",
            "node scripts/validate-modules.js ./src/gep/signals ./src/gep/contextRoutingGene",
        ],
        "constraints": {"max_files": 12, "forbidden_paths": [".git", "node_modules"]},
        "summary": "Compress large skill, agent-type, and MCP instruction lists into route cards, "
        "loading full manuals only after the route is selected.",
        "avoid": [
            "embedding every skill manual because one task might need one of them",
            "inventing skill names or aliases not present in the runtime registry",
            "moving cross-cutting safety policy behind an optional skill loader",
        ],
    },
    {
        "type": "Gene",
        "category": "optimize",
        "schema_version": "1.8.0",
        "epigenetic_marks": [],
        "learning_history": [],
        "anti_patterns": [],
        "routing_hint": {"tier": "mid", "reasoning_level": "medium"},
        "tool_policy": None,
        "id": "gene_claude_transcript_handoff_compression",
        "signals_match": [
            "transcript_context_bloat",
            "conversation_handoff_bloat",
            "pasted_transcript_bloat",
            "随便传一个会话上下文就爆了",
            "会话上下文就爆了",
            "full transcript too large",
        ],
        "preconditions": [
            "A user or agent is transferring conversation context, logs, or transcript "
            "history into a new session",
            "The receiving session needs task continuity, not every raw tool schema or "
            "every previous token",
        ],
        "strategy": [
            "Extract a handoff packet with: objective, current branch/worktree, changed "
            "files, decisions made, commands already run, failing/passing evidence, "
            "blockers, and next irreversible action",
            "Drop raw tool schemas, repeated system prompts, screenshots already summarized, "
            "and low-level logs unless they are direct evidence for a current failure",
            "Keep clickable file paths and exact failing command output snippets; preserve "
            "unresolved errors verbatim enough to reproduce them",
            "Separate durable project memory from ephemeral transcript detail; save durable "
            "facts to memory only when they are non-obvious and future-relevant",
            "Verify the handoff by asking whether an isolated agent can continue from the "
            "packet without reading the original full transcript",
        ],
        "validation": [
            "node --test test/contextSchemaRoutingGene.test.js",
            "node scripts/validate-modules.js ./src/gep/signals ./src/gep/contextRoutingGene",
        ],
        "constraints": {"max_files": 8, "forbidden_paths": [".git", "node_modules"]},
        "summary": "Turn bulky pasted transcripts into compact handoff packets that preserve "
        "decisions, evidence, files, validation, and next actions.",
        "avoid": [
            "copying full transcripts, system prompts, or tool schemas into the next session by "
            "default",
            "dropping exact failing output or branch/worktree state needed to continue safely",
            "saving ephemeral conversation detail as durable memory",
        ],
    },
    {
        "type": "Gene",
        "category": "optimize",
        "schema_version": "1.8.0",
        "epigenetic_marks": [],
        "learning_history": [],
        "anti_patterns": [],
        "routing_hint": {"tier": "mid", "reasoning_level": "medium"},
        "tool_policy": None,
        "id": "gene_claude_memory_index_budget",
        "signals_match": [
            "memory_index_budget",
            "memory_recall_budget",
            "memory_index_bloat",
            "memory_recall_bloat",
            "memory index",
            "memory recall",
            "memory.md too large",
            "memory 索引",
            "memory 全量",
            "MEMORY.md",
        ],
        "preconditions": [
            "Memory index or recalled memory bodies are suspected of consuming too much context",
            "The system has a retrieval path that can inject only top relevant memories "
            "instead of the full memory store",
        ],
        "strategy": [
            "Measure the memory index separately from recalled memory bodies and from "
            "unrelated tool/MCP schema overhead",
            "Keep the index as one-line hooks with links; move detailed facts into "
            "individual memory files retrieved by relevance",
            "Set guardrails: index under roughly 5k tokens is usually acceptable, around 10k "
            "needs pruning, and full memory-body injection must be replaced by retrieval",
            "When pruning, merge duplicate memories and delete stale wrong facts rather than "
            "deleting high-value durable constraints",
            "Validate recall quality with representative prompts before and after pruning so "
            "context savings do not hide important project constraints",
        ],
        "validation": [
            "node --test test/contextSchemaRoutingGene.test.js",
            "node scripts/validate-modules.js ./src/gep/signals ./src/gep/contextRoutingGene",
        ],
        "constraints": {"max_files": 8, "forbidden_paths": [".git", "node_modules"]},
        "summary": "Control memory context cost by keeping MEMORY.md as a lean index and relying on "
        "relevance-based recall for detailed memory bodies.",
        "avoid": [
            "blaming memory before measuring tool/MCP/skill schema overhead separately",
            "injecting every memory body into every session",
            "deleting durable user/project constraints just to make the index look smaller",
        ],
    },
]


def _with_asset_id(template: dict[str, Any]) -> dict[str, Any]:
    gene = dict(template)
    gene["asset_id"] = compute_asset_id(gene)
    return gene


def build_claude_context_schema_routing_gene() -> dict[str, Any]:
    """Legacy single builder — the dispatcher Gene of the family."""
    return _with_asset_id(next(t for t in _FAMILY_TEMPLATES if t["id"] == _DISPATCHER_GENE_ID))


def build_claude_context_gene_family() -> list[dict[str, Any]]:
    """Return the full content-addressed Claude context compression family."""
    return [_with_asset_id(dict(t)) for t in _FAMILY_TEMPLATES]


__all__ = [
    "FAMILY_GENE_IDS",
    "build_claude_context_gene_family",
    "build_claude_context_schema_routing_gene",
]
