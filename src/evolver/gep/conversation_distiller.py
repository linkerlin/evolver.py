"""Conversation → Gene+Capsule distiller (deterministic, no LLM).

Equivalent to ``evolver/src/gep/conversationDistiller.js`` (≈270 lines).
Used by ``POST /v1/a2a/conversation/distill`` and offline distill tooling.
"""

# Signal regex literals and strategy strings mirror Node 1:1 (long by design).
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from typing import Any

from evolver.gep.asset_store import upsert_capsule, upsert_gene
from evolver.gep.content_hash import SCHEMA_VERSION, compute_asset_id
from evolver.gep.sanitize import redact_string, sanitize_payload
from evolver.gep.schemas.gene import create_gene

DEFAULT_SIGNALS: list[str] = []

SIGNAL_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "conversation_distillation",
        re.compile(r"\b(distill|distillation|distilled|蒸馏|提炼|萃取)\b", re.I),
    ),
    ("gene_publish", re.compile(r"\b(gene|capsule|evomap|evolver|gep)\b|基因|胶囊", re.I)),
    (
        "reusable_capability",
        re.compile(
            r"\b(reusable|repeatable|workflow|playbook|capability)\b|可复用|复用|能力|流程", re.I
        ),
    ),
    (
        "visual_annotation",
        re.compile(
            r"\b(screenshot|annotat|mock|wireframe|playwright|visual)\b|截图|圈圈|标注|画图|飞书",
            re.I,
        ),
    ),
    (
        "frontend_polish",
        re.compile(r"\b(frontend|ui|ux|interaction|polish|mockup)\b|前端|交互|打磨|体验", re.I),
    ),
    (
        "proxy_sync",
        re.compile(r"\b(proxy|sync|mailbox|outbound|hub|asset_submit)\b|同步|队列|代理", re.I),
    ),
    (
        "plugin_integration",
        re.compile(
            r"\b(plugin|codex|claude|cursor|antigravity|workbuddy|hook|notify)\b|插件|钩子", re.I
        ),
    ),
    ("test_verified", re.compile(r"\b(test|build|verify|passed|green)\b|测试|验证|通过", re.I)),
]


def trim_text(value: Any, max_len: int) -> str:
    text = redact_string(re.sub(r"\s+", " ", str(value or "")).strip())
    if len(text) > max_len:
        return text[: max_len - 1] + "..."
    return text


def as_array(value: Any) -> list[Any]:
    if not value:
        return []
    return list(value) if isinstance(value, list) else [value]


def normalize_list(value: Any, max_items: int, max_len: int = 180) -> list[str]:
    out: list[str] = []
    for item in as_array(value):
        text = trim_text(item, max_len)
        if text:
            out.append(text)
        if len(out) >= max_items:
            break
    return out


def slugify(value: Any) -> str:
    raw = str(value or "conversation-capability").lower()
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", raw)
    ascii_slug = re.sub(r"^-+|-+$", "", ascii_slug)
    ascii_slug = re.sub(r"-{2,}", "-", ascii_slug)
    if len(ascii_slug) >= 8:
        return re.sub(r"-+$", "", ascii_slug[:56])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    return f"conversation-capability-{digest}"


def hash_input(payload: dict[str, Any]) -> str:
    return hashlib.sha1(
        json.dumps(payload or {}, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:10]


def infer_signals(text: str, provided_signals: Any = None) -> list[str]:
    found: set[str] = set(normalize_list(provided_signals, 12, 64))
    for signal, pattern in SIGNAL_RULES:
        if pattern.search(text):
            found.add(signal)
    if not found:
        found.update(DEFAULT_SIGNALS)
    return list(found)[:12]


def infer_category(signals: list[str], text: str) -> str:
    hay = f"{' '.join(signals)} {text}".lower()
    if re.search(r"proxy|sync|auth|error|failure|bug|repair|修复|故障", hay):
        return "repair"
    if re.search(r"new|plugin|integration|feature|capability|能力|新增", hay):
        return "innovate"
    return "optimize"


def normalize_execution(input_data: dict[str, Any]) -> dict[str, Any]:
    execution_raw = input_data.get("execution")
    execution = execution_raw if isinstance(execution_raw, dict) else {}
    validation = normalize_list(
        input_data.get("validation")
        or input_data.get("verification")
        or execution.get("validation"),
        8,
        180,
    )
    trace: list[dict[str, Any]] = []
    for item in as_array(execution.get("trace")):
        if isinstance(item, str):
            trace.append({"command": trim_text(item, 180), "exit": 0})
            continue
        if not isinstance(item, dict):
            continue
        exit_code = item.get("exit")
        if not isinstance(exit_code, int):
            exit_code = 1 if item.get("ok") is False else 0
        trace.append(
            {
                "command": trim_text(
                    item.get("command") or item.get("cmd") or item.get("name") or "validation", 180
                ),
                "exit": exit_code,
                "summary": trim_text(item.get("summary") or item.get("output") or "", 240),
            }
        )
    for cmd in validation:
        if not any(t.get("command") == cmd for t in trace):
            trace.append({"command": cmd, "exit": 0})
    ok = (
        execution.get("status") == "success"
        or execution.get("ok") is True
        or len(validation) > 0
        or any(t.get("exit") == 0 for t in trace)
    )
    return {
        "status": "success" if ok else "failed",
        "trace": trace,
        "validation": validation,
        "blast_radius": execution.get("blast_radius")
        or input_data.get("blast_radius")
        or {"files": 0, "lines": 0},
    }


def normalize_publish_blast_radius(value: Any, artifact_count: int) -> dict[str, int]:
    files_raw = value.get("files") if isinstance(value, dict) else None
    lines_raw = value.get("lines") if isinstance(value, dict) else None
    try:
        files = float(files_raw) if files_raw is not None else float("nan")
    except (TypeError, ValueError):
        files = float("nan")
    try:
        lines = float(lines_raw) if lines_raw is not None else float("nan")
    except (TypeError, ValueError):
        lines = float("nan")
    files_n = int(files) if not math.isnan(files) else (artifact_count or 1)
    lines_n = int(lines) if not math.isnan(lines) else 1
    return {"files": max(1, files_n), "lines": max(1, lines_n)}


def build_strategy(input_data: dict[str, Any]) -> list[str]:
    explicit = normalize_list(input_data.get("strategy") or input_data.get("steps"), 10, 220)
    if len(explicit) >= 3:
        return explicit
    artifacts = normalize_list(input_data.get("artifacts"), 6, 160)
    strategy = list(explicit)
    strategy.append("Capture the user-visible trigger and the concrete workflow that solved it.")
    strategy.append(
        "Preserve evidence: commands, screenshots, documents, changed files, and validation results."
    )
    if artifacts:
        strategy.append(
            "Link generated artifacts back to the reusable procedure before publishing."
        )
    strategy.append(
        "Sanitize secrets and local-only paths before persisting or submitting the asset."
    )
    strategy.append(
        "Queue the resulting Gene/Capsule through the local Proxy so Hub outages do not drop the learning."
    )
    return strategy[:10]


META_SIGNALS: frozenset[str] = frozenset(
    {
        "conversation_distillation",
        "gene_publish",
        "agent_self_evolution",
        "reusable_capability",
    }
)

META_VOCABULARY: re.Pattern[str] = re.compile(
    r"\b(gene|capsule|distill|reusable|evomap|evolver|self[- ]?evolution)\b|蒸馏|提炼|可复用|基因",
    re.I,
)


CONCRETE_EVIDENCE: re.Pattern[str] = re.compile(
    r"\b(src/|test/|lib/|app/|\.py|\.js|\.ts|\.go|\.rs|\.java|\.rb|\.php)\S*|"
    r"\b(fix|update|add|implement|refactor|debug|patch|modify)\s+\S+\.(py|js|ts|go|rs|java|rb|php)\b",
    re.I,
)


def _is_meta_only(input_data: dict[str, Any], normalized: dict[str, Any]) -> bool:
    """Detect conversations that are ONLY about the evolver mechanism itself.

    Returns True if:
    - All signals are meta signals (about evolver, not domain work), AND
    - No concrete engineering evidence (file paths, code changes), AND
    - Meta vocabulary appears in summary (not just strategy/artifacts)

    This prevents distilling "genes about genes" — self-referential loops
    that don't represent real domain capabilities.
    """
    summary = normalized.get("summary", "")
    strategy_text = " ".join(normalized.get("strategy", []))
    artifacts_text = " ".join(normalized.get("artifacts", []))

    # Check if user provided strategy/artifacts (vs default items added by build_strategy)
    user_provided_strategy = bool(input_data.get("strategy"))
    user_provided_artifacts = bool(
        input_data.get("artifacts") or input_data.get("outputs") or input_data.get("files")
    )

    # Quick check: if no meta vocabulary in summary AND no user-provided strategy/artifacts,
    # then not meta-only (strategy may contain default items with meta vocabulary)
    if (
        not META_VOCABULARY.search(summary)
        and not user_provided_strategy
        and not user_provided_artifacts
    ):
        return False

    full_text = f"{summary} {strategy_text} {artifacts_text}"

    # Check for concrete engineering evidence (file paths, code changes)
    if CONCRETE_EVIDENCE.search(full_text):
        return False

    # Check 1: All inferred signals are meta signals
    signals = normalized.get("signals", [])
    if signals and all(s in META_SIGNALS for s in signals):
        return True

    # Check 2: Meta vocabulary only in strategy/artifacts, not in summary
    meta_in_summary = bool(META_VOCABULARY.search(summary))
    meta_in_strategy = bool(META_VOCABULARY.search(strategy_text))
    meta_in_artifacts = bool(META_VOCABULARY.search(artifacts_text))

    if (meta_in_strategy or meta_in_artifacts) and not meta_in_summary:
        # Meta words only in non-summary fields — likely meta-only discussion
        return True

    # Check 3: Caller-supplied signals are all meta
    caller_signals = input_data.get("signals", [])
    if (
        caller_signals
        and all(s in META_SIGNALS for s in caller_signals)
        and (meta_in_summary or meta_in_strategy)
    ):
        return True

    # Check 4: High density of meta vocabulary in summary with no concrete evidence
    return len(META_VOCABULARY.findall(summary)) >= 3 and not CONCRETE_EVIDENCE.search(summary)


def evaluate_gate(input_data: dict[str, Any], normalized: dict[str, Any]) -> dict[str, Any]:
    # Meta self-reference gate: reject conversations ONLY about evolver itself
    if _is_meta_only(input_data, normalized):
        return {
            "ok": False,
            "score": 0,
            "threshold": 5,
            "reasons": [],
            "reason": "meta_self_reference",
        }

    score = 0
    reasons: list[str] = []
    if len(normalized["summary"]) >= 40:
        score += 2
        reasons.append("summary")
    if len(normalized["strategy"]) >= 3:
        score += 2
        reasons.append("strategy")
    if normalized["artifacts"]:
        score += 1
        reasons.append("artifacts")
    if normalized["execution"]["validation"] or normalized["execution"]["trace"]:
        score += 1
        reasons.append("validation")
    if re.search(
        r"\b(gene|capsule|distill|reusable|evomap|evolver)\b|蒸馏|提炼|可复用|基因",
        normalized["text"],
        re.I,
    ):
        score += 2
        reasons.append("explicit_distill_signal")
    threshold = float(input_data.get("min_score") or input_data.get("minScore") or 5)
    if score < threshold:
        return {
            "ok": False,
            "score": score,
            "threshold": threshold,
            "reasons": reasons,
            "reason": "insufficient_reusable_signal",
        }
    return {"ok": True, "score": score, "threshold": threshold, "reasons": reasons}


def normalize_conversation_input(input_data: dict[str, Any]) -> dict[str, Any]:
    source_text = "\n".join(
        str(part)
        for part in [
            input_data.get("summary"),
            input_data.get("title"),
            input_data.get("user_prompt"),
            input_data.get("userPrompt"),
            input_data.get("assistant_summary"),
            input_data.get("assistantSummary"),
            input_data.get("transcript"),
            input_data.get("conversation"),
        ]
        if part
    )
    text = trim_text(source_text, 8000)
    summary = trim_text(
        input_data.get("summary")
        or input_data.get("assistant_summary")
        or input_data.get("assistantSummary")
        or text,
        300,
    )
    signals = infer_signals(text, input_data.get("signals"))
    strategy = build_strategy(input_data)
    artifacts = normalize_list(
        input_data.get("artifacts") or input_data.get("outputs") or input_data.get("files"),
        12,
        240,
    )
    execution = normalize_execution(input_data)
    return {
        "text": text,
        "summary": summary,
        "signals": signals,
        "strategy": strategy,
        "artifacts": artifacts,
        "execution": execution,
        "platform": trim_text(
            input_data.get("platform") or input_data.get("host") or "generic", 64
        ),
        "source_thread": trim_text(
            input_data.get("thread_id")
            or input_data.get("threadId")
            or input_data.get("session_id")
            or input_data.get("sessionId")
            or "",
            128,
        ),
    }


def _capsule_content(normalized: dict[str, Any]) -> str:
    payload = {
        "platform": normalized["platform"],
        "source_thread": normalized.get("source_thread") or None,
        "artifacts": normalized["artifacts"],
        "excerpt": normalized["text"][:1200],
    }
    # sanitize_payload redacts secrets in the JSON serialization.
    return sanitize_payload(payload)


def distill_conversation(
    input_data: dict[str, Any] | None,
    *,
    persist: bool | None = None,
) -> dict[str, Any]:
    """Distill a conversation payload into a Gene + Capsule.

    *persist* defaults to True unless *input_data.persist* is False.
    """
    if not isinstance(input_data, dict):
        return {"ok": False, "status": "skipped", "reason": "input_object_required"}

    normalized = normalize_conversation_input(input_data)
    if not normalized["summary"] or len(normalized["summary"]) < 20:
        return {"ok": False, "status": "skipped", "reason": "summary_required"}

    gate = evaluate_gate(input_data, normalized)
    if not gate["ok"]:
        return {
            "ok": False,
            "status": "skipped",
            "reason": gate.get("reason"),
            "quality": gate,
            "signals": normalized["signals"],
        }

    slug = slugify(input_data.get("name") or input_data.get("title") or normalized["summary"])
    fingerprint = hash_input(
        {
            "summary": normalized["summary"],
            "signals": normalized["signals"],
            "strategy": normalized["strategy"],
            "artifacts": normalized["artifacts"],
        }
    )

    gene_partial: dict[str, Any] = {
        "id": f"gene_conversation_{slug}_{fingerprint}",
        "summary": normalized["summary"],
        "category": infer_category(normalized["signals"], normalized["text"]),
        "signals_match": normalized["signals"],
        "preconditions": [
            "A live agent conversation produced a repeatable workflow or capability.",
            "The conversation includes enough evidence to reconstruct when and how to use it.",
        ],
        "strategy": normalized["strategy"],
        "validation": (
            normalized["execution"]["validation"]
            if normalized["execution"]["validation"]
            else ["node --version"]
        ),
        "constraints": {
            "max_files": 20,
            "forbidden_paths": [".git", "node_modules", ".env"],
        },
        "schema_version": SCHEMA_VERSION,
        "_source": {
            "kind": "conversation_distillation",
            "platform": normalized["platform"],
            "source_thread": normalized["source_thread"] or None,
            "quality": gate,
            "distilled_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        },
    }
    gene_model = create_gene(gene_partial)
    gene = gene_model.model_dump(by_alias=True)
    # Ensure _source key is present for Node parity (alias dump may use "source").
    if gene.get("source") and not gene.get("_source"):
        gene["_source"] = gene.pop("source")
    gene["type"] = "Gene"
    gene["asset_id"] = compute_asset_id(gene)

    blast = normalize_publish_blast_radius(
        normalized["execution"].get("blast_radius"),
        len(normalized["artifacts"]),
    )
    success = normalized["execution"]["status"] == "success"
    capsule: dict[str, Any] = {
        "type": "Capsule",
        "id": f"capsule_conversation_{slug}_{fingerprint}",
        "schema_version": SCHEMA_VERSION,
        "trigger": list(normalized["signals"]),
        "gene": gene["id"],
        "summary": normalized["summary"],
        "confidence": min(0.95, 0.5 + float(gate["score"]) / 20.0),
        "blast_radius": blast,
        "outcome": {
            "status": normalized["execution"]["status"],
            "score": 0.82 if success else 0.35,
        },
        "success_streak": 1 if success else 0,
        "success_reason": (
            "Conversation included reusable evidence and validation signals." if success else None
        ),
        "source_type": "conversation_distillation",
        "strategy": list(normalized["strategy"]),
        "execution_trace": list(normalized["execution"]["trace"]),
        "a2a": {"eligible_to_broadcast": True},
        "content": _capsule_content(normalized),
        "diff": "",
        "reused_asset_id": "",
        "env_fingerprint": {
            "platform": normalized["platform"],
            "source_thread": normalized["source_thread"] or None,
        },
    }
    capsule["asset_id"] = compute_asset_id(capsule)

    # Node: opts.persist !== false && input.persist !== false
    opts_persist = True if persist is None else bool(persist)
    do_persist = opts_persist and input_data.get("persist") is not False

    if do_persist:
        upsert_gene(gene)
        upsert_capsule(capsule)

    return {
        "ok": True,
        "status": "stored" if do_persist else "draft",
        "distill_id": fingerprint,
        "quality": gate,
        "signals": normalized["signals"],
        "gene": gene,
        "capsule": capsule,
    }


__all__ = [
    "DEFAULT_SIGNALS",
    "distill_conversation",
    "evaluate_gate",
    "infer_signals",
    "normalize_conversation_input",
]
