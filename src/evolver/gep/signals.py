"""Multi-layer signal extraction (regex, keyword scoring, LLM fallback).

Equivalent to evolver/src/gep/signals.js.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any, cast

# Opportunity signal names (shared with mutation.py and personality.py).
OPPORTUNITY_SIGNALS = [
    "user_feature_request",
    "user_improvement_suggestion",
    "perf_bottleneck",
    "capability_gap",
    "stable_success_plateau",
    "external_opportunity",
    "recurring_error",
    "unsupported_input_type",
    "evolution_stagnation_detected",
    "repair_loop_detected",
    "force_innovation_after_repair_loop",
    "tool_bypass",
    "curriculum_target",
    "issue_already_resolved",
    "openclaw_self_healed",
    "empty_cycle_loop_detected",
    "explore_opportunity",
    "hub_search_miss_with_problem",
    "plateau_pivot_required",
    "plateau_pivot_suggested",
]


def has_opportunity_signal(signals: list[str]) -> bool:
    lst = signals if isinstance(signals, list) else []
    for name in OPPORTUNITY_SIGNALS:
        if name in lst:
            return True
        if any(str(s).startswith(name + ":") for s in lst):
            return True
    return False


def analyze_recent_history(recent_events: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Build de-duplication set from recent evolution events."""
    if not isinstance(recent_events, list) or not recent_events:
        return {
            "suppressedSignals": set(),
            "recentIntents": [],
            "consecutiveRepairCount": 0,
            "emptyCycleCount": 0,
            "consecutiveEmptyCycles": 0,
            "consecutiveFailureCount": 0,
            "recentFailureCount": 0,
            "recentFailureRatio": 0.0,
            "signalFreq": {},
            "geneFreq": {},
            "avgScore": None,
            "improving": False,
        }

    recent = recent_events[-10:]

    consecutive_repair_count = 0
    for evt in reversed(recent):
        if evt.get("intent") == "repair":
            consecutive_repair_count += 1
        else:
            break

    signal_freq: dict[str, int] = {}
    gene_freq: dict[str, int] = {}
    tail = recent[-8:]
    for evt in tail:
        sigs = evt.get("signals") or []
        for s in sigs:
            key = str(s)
            if key.startswith("errsig:"):
                key = "errsig"
            elif key.startswith("recurring_errsig"):
                key = "recurring_errsig"
            elif key.startswith("user_feature_request:"):
                key = "user_feature_request"
            elif key.startswith("user_improvement_suggestion:"):
                key = "user_improvement_suggestion"
            signal_freq[key] = signal_freq.get(key, 0) + 1
        for g in evt.get("genes_used") or []:
            gene_freq[str(g)] = gene_freq.get(str(g), 0) + 1

    suppressed_signals = {k for k, v in signal_freq.items() if v >= 3}

    empty_cycle_count = 0
    for evt in tail:
        br = evt.get("blast_radius")
        meta_empty = evt.get("meta", {}).get("empty_cycle")
        if meta_empty or (br and br.get("files") == 0 and br.get("lines") == 0):
            empty_cycle_count += 1

    consecutive_empty_cycles = 0
    for evt in reversed(recent):
        br = evt.get("blast_radius")
        meta_empty = evt.get("meta", {}).get("empty_cycle")
        if meta_empty or (br and br.get("files") == 0 and br.get("lines") == 0):
            consecutive_empty_cycles += 1
        else:
            break

    consecutive_failure_count = 0
    for evt in reversed(recent):
        outcome = evt.get("outcome")
        if outcome and outcome.get("status") == "failed":
            consecutive_failure_count += 1
        else:
            break

    recent_failure_count = sum(
        1 for evt in tail if evt.get("outcome", {}).get("status") == "failed"
    )

    recent_scores = [
        e.get("outcome", {}).get("score")
        for e in recent_events[-6:]
        if isinstance(e.get("outcome", {}).get("score"), (int, float))
        and e["outcome"]["score"] >= 0
    ]
    avg_score = sum(recent_scores) / len(recent_scores) if recent_scores else None
    improving = len(recent_scores) >= 2 and recent_scores[-1] > recent_scores[-2] + 0.05

    return {
        "suppressedSignals": suppressed_signals,
        "recentIntents": [e.get("intent", "unknown") for e in recent],
        "consecutiveRepairCount": consecutive_repair_count,
        "emptyCycleCount": empty_cycle_count,
        "consecutiveEmptyCycles": consecutive_empty_cycles,
        "consecutiveFailureCount": consecutive_failure_count,
        "recentFailureCount": recent_failure_count,
        "recentFailureRatio": recent_failure_count / len(tail) if tail else 0.0,
        "signalFreq": signal_freq,
        "geneFreq": gene_freq,
        "avgScore": avg_score,
        "improving": improving,
    }


# ---------------------------------------------------------------------------
# Layer 2: Weighted keyword scoring
# ---------------------------------------------------------------------------
SIGNAL_PROFILES = {
    "perf_bottleneck": {
        "keywords": {
            "slow": 3,
            "timeout": 4,
            "timed out": 4,
            "latency": 3,
            "bottleneck": 5,
            "lag": 2,
            "delay": 2,
            "hung": 3,
            "freeze": 3,
            "unresponsive": 4,
            "took too long": 4,
            "high cpu": 4,
            "high memory": 4,
            "oom": 5,
            "out of memory": 5,
            "performance": 2,
            "throttle": 3,
        },
        "threshold": 6,
    },
    "capability_gap": {
        "keywords": {
            "not supported": 5,
            "cannot": 1,
            "unsupported": 4,
            "not implemented": 5,
            "no way to": 3,
            "missing feature": 5,
            "not available": 3,
            "no support for": 4,
            "unavailable": 3,
            "incompatible": 3,
        },
        "threshold": 5,
    },
    "user_feature_request": {
        "keywords": {
            "add": 1,
            "implement": 3,
            "create": 2,
            "build": 2,
            "feature": 3,
            "i want": 3,
            "i need": 3,
            "we need": 3,
            "please add": 4,
            "new function": 4,
            "new module": 4,
            "endpoint": 2,
            "capability": 2,
            "support for": 2,
        },
        "threshold": 6,
    },
    "user_improvement_suggestion": {
        "keywords": {
            "improve": 3,
            "enhance": 3,
            "upgrade": 3,
            "refactor": 4,
            "clean up": 3,
            "simplify": 3,
            "streamline": 3,
            "optimize": 3,
            "could be better": 4,
            "should be": 2,
            "more efficient": 3,
        },
        "threshold": 5,
    },
    "recurring_error": {
        "keywords": {
            "error": 1,
            "exception": 2,
            "failed": 1,
            "crash": 4,
            "again": 1,
            "still": 1,
            "keeps": 2,
            "repeatedly": 4,
            "same error": 5,
            "still failing": 5,
            "not fixed": 4,
        },
        "threshold": 7,
    },
    "tool_bypass": {
        "keywords": {
            "exec": 2,
            "shell": 2,
            "subprocess": 3,
            "child_process": 3,
            "curl": 2,
            "wget": 2,
            "ad-hoc": 3,
            "workaround": 3,
            "hack": 2,
            "manual": 1,
        },
        "threshold": 6,
    },
    "evolution_stagnation_detected": {
        "keywords": {
            "no change": 4,
            "same result": 4,
            "stuck": 3,
            "plateau": 4,
            "stagnant": 5,
            "no progress": 5,
            "spinning": 3,
            "idle": 2,
            "nothing new": 4,
            "exhausted": 3,
        },
        "threshold": 6,
    },
}


def _extract_keyword_score(lower: str) -> list[str]:
    scored: list[str] = []
    for signal_name, profile in SIGNAL_PROFILES.items():
        keywords = cast(dict[str, int], profile["keywords"])
        threshold = cast(int, profile["threshold"])
        total = 0
        for kw, weight in keywords.items():
            idx = 0
            count = 0
            while idx < len(lower) and count < 20:
                pos = lower.find(kw, idx)
                if pos == -1:
                    break
                count += 1
                idx = pos + len(kw)
            total += count * weight
        if total >= threshold:
            scored.append(signal_name)
    return scored


# ---------------------------------------------------------------------------
# Layer 3: LLM semantic analysis (rate-limited, optional)
# ---------------------------------------------------------------------------
_llm_signal_cycle_count = 0
LLM_SIGNAL_INTERVAL = 5


def _extract_llm(corpus: str) -> list[str]:
    global _llm_signal_cycle_count
    _llm_signal_cycle_count += 1
    if _llm_signal_cycle_count % LLM_SIGNAL_INTERVAL != 1:
        return []

    try:
        # Lazy import to avoid heavy deps during signal extraction
        from evolver.gep.a2a_protocol import get_hub_node_secret, get_hub_url, get_node_id

        hub_url = get_hub_url()
        node_secret = get_hub_node_secret()
        if not hub_url or not node_secret:
            return []

        summary = corpus[:2000]
        post_data = json.dumps(
            {
                "corpus_summary": summary,
                "signal_types": OPPORTUNITY_SIGNALS,
                "sender_id": get_node_id(),
            },
            ensure_ascii=False,
        )
        url = hub_url.rstrip("/") + "/a2a/signal/analyze"

        result = subprocess.run(
            [
                "curl",
                "-s",
                "-m",
                "10",
                "-X",
                "POST",
                "-H",
                "Content-Type: application/json",
                "-H",
                f"Authorization: Bearer {node_secret}",
                "-d",
                post_data,
                url,
            ],
            capture_output=True,
            text=True,
            timeout=12,
        )
        if result.returncode != 0 or not result.stdout:
            return []
        parsed = json.loads(result.stdout)
        if isinstance(parsed.get("signals"), list):
            return [str(s) for s in parsed["signals"] if isinstance(s, str) and 0 < len(s) < 200][
                :10
            ]
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------
def _merge_signals(
    regex_signals: list[str],
    score_signals: list[str],
    llm_signals: list[str],
) -> list[str]:
    merged_set = set(regex_signals) | set(score_signals) | set(llm_signals)
    score_only = [s for s in score_signals if s not in regex_signals]
    llm_only = [s for s in llm_signals if s not in regex_signals and s not in score_signals]
    overlap = [s for s in regex_signals if s in score_signals or s in llm_signals]

    if score_only or llm_only or overlap:
        print(
            f"[Signals] Multi-strategy: regex={len(regex_signals)}, "
            f"score={len(score_signals)}, llm={len(llm_signals)}, merged={len(merged_set)}"
            f"{' | score-only: ' + ', '.join(score_only) if score_only else ''}"
            f"{' | llm-only: ' + ', '.join(llm_only) if llm_only else ''}"
            f"{' | confirmed: ' + ', '.join(overlap) if overlap else ''}"
        )

    return list(merged_set)


# ---------------------------------------------------------------------------
# Layer 1: Regex pattern matching
# ---------------------------------------------------------------------------
_ERROR_LINE_RE = re.compile(
    r"\b(typeerror|referenceerror|syntaxerror)\b\s*:"
    r"|error\s*:|exception\s*:"
    r"|\[error"
    r"|错误\s*[：:]"
    r"|异常\s*[：:]"
    r"|报错\s*[：:]"
    r"|失败\s*[：:]",
    re.IGNORECASE,
)


def _extract_regex(corpus: str, lower: str, error_hit: bool) -> list[str]:
    signals: list[str] = []

    if error_hit:
        signals.append("log_error")

    try:
        lines = [l.strip() for l in corpus.split("\n") if l.strip()]
        err_line = next((l for l in lines if _ERROR_LINE_RE.search(l)), None)
        if err_line:
            clipped = re.sub(r"\s+", " ", err_line)[:260]
            signals.append("errsig:" + clipped)
    except Exception:
        pass

    if "memory.md missing" in lower:
        signals.append("memory_missing")
    if "user.md missing" in lower:
        signals.append("user_missing")
    if "key missing" in lower:
        signals.append("integration_key_missing")
    if "no session logs found" in lower or "no jsonl files" in lower:
        signals.append("session_logs_missing")
    if os.name == "nt" and any(k in lower for k in ("pgrep", "ps aux", "cat >", "heredoc")):
        signals.append("windows_shell_incompatible")
    if "path.resolve(__dirname, '../../../" in lower:
        signals.append("path_outside_workspace")

    if "prompt" in lower and "evolutionevent" not in lower:
        signals.append("protocol_drift")

    # Recurring error detection
    try:
        err_patterns = re.findall(
            r'(?:LLM error|"error"|"status":\s*"error")[^}]{0,200}',
            corpus,
            re.IGNORECASE,
        )
        error_counts: dict[str, int] = {}
        for ep in err_patterns:
            key = re.sub(r"\s+", " ", ep)[:100]
            error_counts[key] = error_counts.get(key, 0) + 1
        recurring = [(k, v) for k, v in error_counts.items() if v >= 3]
        if recurring:
            signals.append("recurring_error")
            top = sorted(recurring, key=lambda x: x[1], reverse=True)[0]
            signals.append(f"recurring_errsig({top[1]}x):{top[0][:150]}")
    except Exception:
        pass

    if re.search(r"unsupported mime|unsupported.*type|invalid.*mime", lower, re.IGNORECASE):
        signals.append("unsupported_input_type")

    # Feature request (4 languages)
    feature_snippet = ""
    feat_en = re.search(
        r"\b(add|implement|create|build|make|develop|write|design)\b[^.?!\n]{3,120}\b(feature|function|module|capability|tool|support|endpoint|command|option|mode)\b",
        corpus,
        re.IGNORECASE,
    )
    if feat_en:
        feature_snippet = re.sub(r"\s+", " ", feat_en.group(0)).strip()[:200]
    if not feature_snippet and re.search(
        r"\b(i want|i need|we need|please add|can you add|could you add|let'?s add)\b",
        lower,
        re.IGNORECASE,
    ):
        _feat_want_pat = (
            r".{0,80}\b(i want|i need|we need|please add|can you add|"
            r"could you add|let'?s add)\b.{0,80}"
        )
        feat_want = re.search(_feat_want_pat, corpus, re.IGNORECASE)
        feature_snippet = (
            re.sub(r"\s+", " ", feat_want.group(0)).strip()[:200]
            if feat_want
            else "feature request"
        )
    if not feature_snippet and re.search(
        r"加个|实现一下|做个|想要\s*一个|需要\s*一个|帮我加|帮我开发|加一下|新增一个|加个功能|做个功能|我想",
        corpus,
    ):
        feat_zh = re.search(
            r".{0,100}(加个|实现一下|做个|想要\s*一个|需要\s*一个|帮我加|帮我开发|加一下|新增一个|加个功能|做个功能).{0,100}",
            corpus,
        )
        if feat_zh:
            feature_snippet = re.sub(r"\s+", " ", feat_zh.group(0)).strip()[:200]
        if not feature_snippet and "我想" in corpus:
            feat_want_zh = re.search(r"我想\s*[，,\.。、\s]*([\s\S]{0,400})", corpus)
            feature_snippet = (
                re.sub(r"\s+", " ", feat_want_zh.group(1)).strip()[:200]
                if feat_want_zh and feat_want_zh.group(1).strip()
                else "功能需求"
            )
        if not feature_snippet:
            feature_snippet = "功能需求"
    if not feature_snippet and re.search(
        r"加個|實現一下|做個|想要一個|請加|新增一個|加個功能|做個功能|幫我加",
        corpus,
    ):
        feat_tw = re.search(
            r".{0,100}(加個|實現一下|做個|想要一個|請加|新增一個|加個功能|做個功能|幫我加).{0,100}",
            corpus,
        )
        feature_snippet = (
            re.sub(r"\s+", " ", feat_tw.group(0)).strip()[:200] if feat_tw else "功能需求"
        )
    if not feature_snippet and re.search(
        r"追加|実装|作って|機能を|追加して|が欲しい|を追加|してほしい",
        corpus,
    ):
        feat_ja = re.search(
            r".{0,100}(追加|実装|作って|機能を|追加して|が欲しい|を追加|してほしい).{0,100}",
            corpus,
        )
        feature_snippet = (
            re.sub(r"\s+", " ", feat_ja.group(0)).strip()[:200] if feat_ja else "機能要望"
        )

    has_feature = bool(
        feature_snippet
        or re.search(
            r"\b(add|implement|create|build|make|develop|write|design)\b[^.?!\n]{3,60}\b(feature|function|module|capability|tool|support|endpoint|command|option|mode)\b",
            corpus,
            re.IGNORECASE,
        )
        or re.search(
            r"\b(i want|i need|we need|please add|can you add|could you add|let'?s add)\b",
            lower,
            re.IGNORECASE,
        )
        or re.search(
            r"加个|实现一下|做个|想要\s*一个|需要\s*一个|帮我加|帮我开发|加一下|新增一个|加个功能|做个功能|我想",
            corpus,
        )
        or re.search(
            r"加個|實現一下|做個|想要一個|請加|新增一個|加個功能|做個功能|幫我加",
            corpus,
        )
        or re.search(
            r"追加|実装|作って|機能を|追加して|が欲しい|を追加|してほしい",
            corpus,
        )
    )
    if has_feature:
        signals.append("user_feature_request")
        if feature_snippet:
            signals.append("user_feature_request:" + feature_snippet)

    # Improvement suggestion (4 languages)
    improvement_snippet = ""
    if not error_hit:
        _imp_en_pat = (
            r".{0,80}\b(should be|could be better|improve|enhance|upgrade|"
            r"refactor|clean up|simplify|streamline)\b.{0,80}"
        )
        imp_en = re.search(_imp_en_pat, corpus, re.IGNORECASE)
        if imp_en:
            improvement_snippet = re.sub(r"\s+", " ", imp_en.group(0)).strip()[:200]
        if not improvement_snippet and re.search(
            r"改进一下|优化一下|简化|重构|整理一下|弄得更好",
            corpus,
        ):
            imp_zh = re.search(
                r".{0,100}(改进一下|优化一下|简化|重构|整理一下|弄得更好).{0,100}",
                corpus,
            )
            improvement_snippet = (
                re.sub(r"\s+", " ", imp_zh.group(0)).strip()[:200] if imp_zh else "改进建议"
            )
        if not improvement_snippet and re.search(
            r"改進一下|優化一下|簡化|重構|整理一下|弄得更好",
            corpus,
        ):
            imp_tw = re.search(
                r".{0,100}(改進一下|優化一下|簡化|重構|整理一下|弄得更好).{0,100}",
                corpus,
            )
            improvement_snippet = (
                re.sub(r"\s+", " ", imp_tw.group(0)).strip()[:200] if imp_tw else "改進建議"
            )
        if not improvement_snippet and re.search(
            r"改善|最適化|簡素化|リファクタ|良くして|改良",
            corpus,
        ):
            imp_ja = re.search(
                r".{0,100}(改善|最適化|簡素化|リファクタ|良くして|改良).{0,100}",
                corpus,
            )
            improvement_snippet = (
                re.sub(r"\s+", " ", imp_ja.group(0)).strip()[:200] if imp_ja else "改善要望"
            )

        has_improvement = bool(
            improvement_snippet
            or re.search(
                r"\b(should be|could be better|improve|enhance|upgrade|"
                r"refactor|clean up|simplify|streamline)\b",
                lower,
                re.IGNORECASE,
            )
            or re.search(r"改进一下|优化一下|简化|重构|整理一下|弄得更好", corpus)
            or re.search(r"改進一下|優化一下|簡化|重構|整理一下|弄得更好", corpus)
            or re.search(r"改善|最適化|簡素化|リファクタ|良くして|改良", corpus)
        )
        if has_improvement:
            signals.append("user_improvement_suggestion")
            if improvement_snippet:
                signals.append("user_improvement_suggestion:" + improvement_snippet)

    _perf_pat = (
        r"\b(slow|timeout|timed?\s*out|latency|bottleneck|took too long|"
        r"performance issue|high cpu|high memory|oom|out of memory)\b"
    )
    if re.search(_perf_pat, lower, re.IGNORECASE):
        signals.append("perf_bottleneck")

    _cap_gap_pat = (
        r"\b(not supported|cannot|doesn'?t support|no way to|missing feature|"
        r"unsupported|not available|not implemented|no support for)\b"
    )
    if re.search(_cap_gap_pat, lower, re.IGNORECASE):
        if not any(
            s in signals for s in ("memory_missing", "user_missing", "session_logs_missing")
        ):
            signals.append("capability_gap")

    # Tool usage analytics
    tool_usage: dict[str, int] = {}
    tool_matches = re.findall(r"\[TOOL:\s*([\w-]+)\]", corpus)
    exec_commands = re.findall(r"exec: (node\s+[\w\/\.-]+\.js\s+ensure)", corpus)
    benign_exec_count = len(exec_commands)

    for tool_name in tool_matches:
        tool_usage[tool_name] = tool_usage.get(tool_name, 0) + 1
    if "exec" in tool_usage:
        tool_usage["exec"] = max(0, tool_usage["exec"] - benign_exec_count)

    for tool, count in tool_usage.items():
        if count >= 10:
            signals.append(f"high_tool_usage:{tool}")
        if tool == "exec" and count >= 5:
            signals.append("repeated_tool_usage:exec")

    # Tool bypass detection
    bypass_patterns = [
        re.compile(r"node\s+\S+\.m?js"),
        re.compile(r"npx\s+"),
        re.compile(r"curl\s+.*api", re.IGNORECASE),
        re.compile(r"python\s+\S+\.py"),
    ]
    exec_content = re.findall(r"exec:.*$", corpus, re.MULTILINE)
    for line in exec_content:
        for pat in bypass_patterns:
            if pat.search(line):
                signals.append("tool_bypass")
                break
        else:
            continue
        break

    return signals


# ---------------------------------------------------------------------------
# Multi-strategy orchestrator
# ---------------------------------------------------------------------------
def extract_signals(
    *,
    recent_session_transcript: str = "",
    today_log: str = "",
    memory_snippet: str = "",
    user_snippet: str = "",
    recent_events: list[dict[str, Any]] | None = None,
) -> list[str]:
    corpus = "\n".join(
        [
            str(recent_session_transcript or ""),
            str(today_log or ""),
            str(memory_snippet or ""),
            str(user_snippet or ""),
        ]
    )
    lower = corpus.lower()

    history = analyze_recent_history(recent_events or [])

    error_hit = bool(
        re.search(
            r'\[error\]|error:|exception:|iserror":true|"status":\s*"error"|"status":\s*"failed"|错误\s*[：:]|异常\s*[：:]|报错\s*[：:]|失败\s*[：:]',
            lower,
            re.IGNORECASE,
        )
    )

    regex_signals = _extract_regex(corpus, lower, error_hit)
    score_signals = _extract_keyword_score(lower)
    llm_signals = _extract_llm(corpus)

    signals = _merge_signals(regex_signals, score_signals, llm_signals)

    # Signal prioritization: remove cosmetic signals when actionable ones exist
    actionable = [
        s
        for s in signals
        if s
        not in (
            "user_missing",
            "memory_missing",
            "session_logs_missing",
            "windows_shell_incompatible",
        )
    ]
    if actionable:
        signals = actionable

    # History-based dedup
    if history["suppressedSignals"]:
        before = len(signals)

        def _normalize_key(s: str) -> str:
            if s.startswith("errsig:"):
                return "errsig"
            if s.startswith("recurring_errsig"):
                return "recurring_errsig"
            if s.startswith("user_feature_request:"):
                return "user_feature_request"
            if s.startswith("user_improvement_suggestion:"):
                return "user_improvement_suggestion"
            return s

        signals = [s for s in signals if _normalize_key(s) not in history["suppressedSignals"]]
        if before > 0 and not signals:
            signals.extend(["evolution_stagnation_detected", "stable_success_plateau"])

    # Force innovation after 3+ consecutive repairs
    if history["consecutiveRepairCount"] >= 3:
        signals = [
            s
            for s in signals
            if s != "log_error"
            and not s.startswith("errsig:")
            and not s.startswith("recurring_errsig")
        ]
        if not signals:
            signals.extend(["repair_loop_detected", "stable_success_plateau"])
        signals.append("force_innovation_after_repair_loop")

    # Empty cycle loop
    if history["emptyCycleCount"] >= 4:
        signals = [
            s
            for s in signals
            if s != "log_error"
            and not s.startswith("errsig:")
            and not s.startswith("recurring_errsig")
        ]
        if "empty_cycle_loop_detected" not in signals:
            signals.append("empty_cycle_loop_detected")
        if "stable_success_plateau" not in signals:
            signals.append("stable_success_plateau")

    # Saturation
    if history["consecutiveEmptyCycles"] >= 5:
        if "force_steady_state" not in signals:
            signals.append("force_steady_state")
        if "evolution_saturation" not in signals:
            signals.append("evolution_saturation")
    elif history["consecutiveEmptyCycles"] >= 3:
        if "evolution_saturation" not in signals:
            signals.append("evolution_saturation")

    if history["consecutiveEmptyCycles"] >= 3 and "explore_opportunity" not in signals:
        signals.append("explore_opportunity")

    # Failure streak
    if history["consecutiveFailureCount"] >= 3:
        signals.append(f"consecutive_failure_streak_{history['consecutiveFailureCount']}")
        if history["consecutiveFailureCount"] >= 5:
            signals.append("failure_loop_detected")
            top_gene = (
                max(history["geneFreq"], key=lambda k: history["geneFreq"][k])
                if history["geneFreq"]
                else None
            )
            if top_gene:
                signals.append(f"ban_gene:{top_gene}")

    if history["recentFailureRatio"] >= 0.75:
        signals.extend(["high_failure_ratio", "force_innovation_after_repair_loop"])

    # Plateau from scores
    avg_score = history.get("avgScore")
    improving = history.get("improving", False)
    if avg_score is not None:
        if avg_score < 0.35 and not improving:
            signals.append("plateau_pivot_required")
        elif avg_score < 0.55 and not improving and history["consecutiveRepairCount"] >= 2:
            signals.append("plateau_pivot_suggested")

    if not signals or all(
        s
        in ("user_missing", "memory_missing", "session_logs_missing", "windows_shell_incompatible")
        for s in signals
    ):
        signals = ["stable_success_plateau"]

    return list(dict[str, Any].fromkeys(signals))


SKIP_HUB_SATURATION_SIGNALS = {
    "evolution_saturation",
    "force_steady_state",
    "empty_cycle_loop_detected",
    "failure_loop_detected",
}


def should_skip_hub_calls(signals: list[str] | None) -> bool:
    """Return True when saturation signals dominate and there are no actionable signals."""
    if not isinstance(signals, list) or not signals:
        return False
    has_saturation = any(s in SKIP_HUB_SATURATION_SIGNALS for s in signals)
    actionable = any(
        s not in SKIP_HUB_SATURATION_SIGNALS and not s.startswith("ban_gene:") for s in signals
    )
    return has_saturation and not actionable


__all__ = [
    "LLM_SIGNAL_INTERVAL",
    "OPPORTUNITY_SIGNALS",
    "SIGNAL_PROFILES",
    "_extract_keyword_score",
    "_extract_llm",
    "_extract_regex",
    "_merge_signals",
    "analyze_recent_history",
    "extract_signals",
    "has_opportunity_signal",
    "should_skip_hub_calls",
]
