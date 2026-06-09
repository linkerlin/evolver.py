"""Gene / capsule selector based on signal matching.

Equivalent to evolver/src/gep/selector.js (obfuscated).
"""

from __future__ import annotations

import math
import random
import re
from typing import Any

from evolver.config import GENE_EPIGENETIC_HARD_BOOST
from evolver.gep.env_fingerprint import capture_env_fingerprint, env_fingerprint_key


def tokenize(text: str) -> list[str]:
    """Unicode-aware tokenization: keep CJK/JA/KO, split on ASCII punctuation/space."""
    if not text:
        return []
    # Split on non-alphanumeric non-CJK runs
    tokens = re.split(r"[^\w\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af]+", text, flags=re.UNICODE)
    out = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        # Lowercase ASCII only
        lowered = ""
        for ch in t:
            lowered += ch.lower() if "a" <= ch <= "z" else ch
        out.append(lowered)
    return out


def _match_pattern_to_signals(pattern: str, signals: list[str]) -> bool:
    """Match a pattern to signals. Supports pipe aliases and substring matching."""
    aliases = [a.strip() for a in pattern.split("|") if a.strip()]
    for signal in signals:
        sig = str(signal).lower()
        # Strip detail suffix for baseName:snippet signals
        base = sig.split(":", 1)[0]
        for alias in aliases:
            a = alias.lower()
            if a == sig or a == base or a in sig:
                return True
    return False


def _score_gene(gene: dict, signals: list[str]) -> float:
    score = 0.0
    signals_match = gene.get("signals_match") or []
    for pattern in signals_match:
        if _match_pattern_to_signals(pattern, signals):
            score += 1.0

    # Boost for derived learning tags (simple keyword overlap)
    summary = gene.get("summary", "")
    for signal in signals:
        tokens = tokenize(signal)
        for tok in tokens:
            if len(tok) > 2 and tok.lower() in summary.lower():
                score += 0.1

    # Downweight anti-patterns
    anti_patterns = gene.get("anti_patterns") or []
    hard_fail_count = sum(
        1
        for ap in anti_patterns
        if isinstance(ap, dict) and ap.get("mode") == "hard" and "problem" in (ap.get("learning_signals") or [])
    )
    score -= hard_fail_count * 0.4

    # Upweight learning history success
    learning_history = gene.get("learning_history") or []
    success_count = sum(1 for lh in learning_history if isinstance(lh, dict) and lh.get("outcome") == "success")
    score += success_count * 0.15

    return max(0.0, score)


def compute_drift_intensity(
    *,
    drift_enabled: bool,
    gene_pool_size: int,
    memory_evidence: int = 0,
) -> float:
    ne = max(1, gene_pool_size)
    base = min(1.0, 1.0 / math.sqrt(ne))
    if drift_enabled:
        offset = max(0.02, 0.3 - memory_evidence / 200.0)
        return min(1.0, base + offset)
    return base


def is_epigenetically_suppressed(gene: dict, env: dict[str, str] | None = None) -> bool:
    marks = gene.get("epigenetic_marks") or []
    if not marks:
        return False
    if env is None:
        env = capture_env_fingerprint()
    key = env_fingerprint_key(env)
    for mark in marks:
        if not isinstance(mark, dict):
            continue
        if mark.get("context") == key:
            boost = mark.get("boost")
            if isinstance(boost, (int, float)) and boost <= GENE_EPIGENETIC_HARD_BOOST:
                return True
    return False


def select_gene(
    genes: list[dict],
    signals: list[str],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = options or {}
    banned: set[str] = options.get("bannedGeneIds") or set()
    preferred = options.get("preferredGeneId")
    drift_enabled = bool(options.get("driftEnabled", False))
    effective_pop = options.get("effectivePopulationSize", max(1, len(genes)))
    memory_evidence = options.get("memoryEvidence", 0)

    drift_intensity = compute_drift_intensity(
        drift_enabled=drift_enabled,
        gene_pool_size=effective_pop,
        memory_evidence=memory_evidence,
    )

    candidates = []
    for gene in genes:
        gid = gene.get("id")
        if not gid:
            continue
        if gid in banned:
            continue
        if is_epigenetically_suppressed(gene):
            continue
        score = _score_gene(gene, signals)
        if score > 0:
            candidates.append({"gene": gene, "score": score})

    # Apply preferred gene multiplier
    if preferred:
        for c in candidates:
            if c["gene"].get("id") == preferred:
                c["score"] *= 1.5

    # Apply drift jitter
    if drift_enabled:
        for c in candidates:
            c["score"] += random.random() * drift_intensity

    candidates.sort(key=lambda x: x["score"], reverse=True)

    if not candidates:
        # Distilled gene fallback
        for gene in genes:
            gid = gene.get("id")
            if not gid or gid in banned:
                continue
            if is_epigenetically_suppressed(gene):
                continue
            if "distilled" in gid or "s2g" in gid:
                return {
                    "selected": gene,
                    "alternatives": [],
                    "driftIntensity": drift_intensity,
                    "driftMode": "distilled_fallback",
                    "score": 0.1,
                }
        return {
            "selected": None,
            "alternatives": [],
            "driftIntensity": drift_intensity,
            "driftMode": "none",
            "score": 0.0,
        }

    selected = candidates[0]["gene"]
    alternatives = [c["gene"] for c in candidates[1:4]]
    return {
        "selected": selected,
        "alternatives": alternatives,
        "driftIntensity": drift_intensity,
        "driftMode": "score_ranked",
        "score": candidates[0]["score"],
    }


def select_capsule(capsules: list[dict], signals: list[str]) -> dict | None:
    best: dict | None = None
    best_score = 0.0
    for cap in capsules:
        triggers = cap.get("trigger") or []
        score = sum(1.0 for t in triggers if any(t.lower() in str(s).lower() for s in signals))
        if score > best_score:
            best_score = score
            best = cap
    return best


def select_gene_and_capsule(ctx: dict[str, Any]) -> dict[str, Any]:
    genes = ctx.get("genes") or []
    capsules = ctx.get("capsules") or []
    signals = ctx.get("signals") or []
    memory_advice = ctx.get("memoryAdvice") or {}
    drift_enabled = bool(ctx.get("driftEnabled", False))

    banned = set(memory_advice.get("bannedGeneIds") or [])
    preferred = memory_advice.get("preferredGeneId")
    memory_evidence = memory_advice.get("totalAttempts", 0)

    selector = select_gene(
        genes,
        signals,
        {
            "bannedGeneIds": banned,
            "preferredGeneId": preferred,
            "driftEnabled": drift_enabled,
            "memoryEvidence": memory_evidence,
        },
    )

    selected_gene = selector.get("selected")
    selected_capsule = None
    if selected_gene:
        selected_capsule = select_capsule(capsules, signals)

    memory_used = bool(preferred or banned)
    memory_evidence_count = memory_advice.get("totalAttempts", 0)

    return {
        "selectedGene": selected_gene,
        "selectedCapsule": selected_capsule,
        "selector": selector,
        "selectionPath": selector.get("driftMode", "score_ranked"),
        "memoryUsed": memory_used,
        "memoryEvidence": memory_evidence_count,
    }


__all__ = [
    "tokenize",
    "compute_drift_intensity",
    "is_epigenetically_suppressed",
    "select_gene",
    "select_capsule",
    "select_gene_and_capsule",
]
