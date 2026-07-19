"""Persona cycle commentary — human-readable evolution summaries for 3 personas.

Equivalent to ``evolver/src/ops/commentary.js``.
Generates short (< 140 chars) and verbose commentary after each solidify cycle,
in three distinct voices: pragmatist, explorer, and critic.
"""

from __future__ import annotations

from typing import Any

_PERSONAS = ("pragmatist", "explorer", "critic")


def _signal_summary(signals: list[str]) -> str:
    if not signals:
        return "无触发信号"
    top = signals[:3]
    s = "、".join(str(x) for x in top)
    if len(signals) > 3:
        s += f" 等 {len(signals)} 项"
    return s


def _blast_text(blast_radius: dict[str, Any]) -> str:
    files = blast_radius.get("files", 0)
    lines = blast_radius.get("lines", 0)
    if files == 0:
        return "无损变更"
    return f"涉及 {files} 个文件、{lines} 行"


def _outcome_label(outcome: dict[str, Any]) -> str:
    status = outcome.get("status", "?")
    score = outcome.get("score")
    if score is not None:
        return f"{status} (分数 {score})"
    return str(status)


def _risk_label(mutation: dict[str, Any]) -> str:
    level = mutation.get("risk_level", "?")
    labels = {"low": "低危", "medium": "中危", "high": "高危"}
    return labels.get(level, str(level))


# ---------------------------------------------------------------------------
# Persona generators
# ---------------------------------------------------------------------------


def _pragmatist_short(event: dict[str, Any]) -> str:
    gene_id = event.get("gene_id", "?")
    mutation = event.get("mutation") or {}
    category = mutation.get("category", "?")
    blast_radius = event.get("blast_radius", {})
    outcome = event.get("outcome") or {}
    risk = _risk_label(mutation)
    blast = _blast_text(blast_radius)
    status = outcome.get("status", "?")
    return f"[{risk}] 基因 {gene_id} ({category}) {status}：{blast}。"


def _pragmatist_verbose(event: dict[str, Any]) -> str:
    gene_id = event.get("gene_id", "?")
    mutation = event.get("mutation") or {}
    signals = event.get("signals", [])
    blast_radius = event.get("blast_radius", {})
    outcome = event.get("outcome") or {}
    risk = _risk_label(mutation)
    signal_text = _signal_summary(signals)
    outcome_text = _outcome_label(outcome)
    blast = _blast_text(blast_radius)
    lines = [
        "=== Pragmatist 评述 ===",
        f"基因: {gene_id} | 类别: {mutation.get('category', '?')} | 风险: {risk}",
        f"触发信号: {signal_text}",
        f"结果: {outcome_text} | 变更范围: {blast}",
    ]
    if outcome.get("status") == "success":
        lines.append("评估: 有效执行，可考虑加固（solidify）。")
    elif outcome.get("status") == "failed":
        lines.append("评估: 执行失败，建议回滚并检查预检条件。")
    else:
        lines.append("评估: 结果不确定，等待进一步验证。")
    return "\n".join(lines)


def _explorer_short(event: dict[str, Any]) -> str:
    gene_id = event.get("gene_id", "?")
    mutation = event.get("mutation") or {}
    category = mutation.get("category", "?")
    cat_cn = {"repair": "修复", "optimize": "优化", "innovate": "创新", "default": "??"}
    outcome = event.get("outcome") or {}
    status = outcome.get("status", "?")
    status_cn = {"success": "成功", "failed": "失败"}
    cat_label = cat_cn.get(category, category)
    st_label = status_cn.get(status, status)
    return f"基因 {gene_id} 尝试{cat_label}策略，结果{st_label}——下一步将如何演化？"


def _explorer_verbose(event: dict[str, Any]) -> str:
    gene_id = event.get("gene_id", "?")
    mutation = event.get("mutation") or {}
    signals = event.get("signals", [])
    outcome = event.get("outcome") or {}
    blast_radius = event.get("blast_radius", {})
    signal_text = _signal_summary(signals)
    outcome_text = _outcome_label(outcome)
    blast = _blast_text(blast_radius)
    reason = _pragmatist_short(event)
    lines = [
        "=== Explorer 评述 ===",
        f"基因 {gene_id} 在本周期选择了 {mutation.get('category', '?')} 路径。",
        f"驱动因素: {signal_text}",
        f"产出: {outcome_text}，{blast}",
        f"推理: {reason}",
    ]
    if mutation.get("category") == "innovate":
        lines.append("创新尝试——高风险、高回报。密切关注后续 cycle 的适应度变化。")
    elif mutation.get("category") == "repair":
        lines.append("修复倾向——系统在收敛。这是短期主义还是长期稳健策略？")
    else:
        lines.append("中性策略——观察是否有未开发的进化方向。")
    return "\n".join(lines)


def _critic_short(event: dict[str, Any]) -> str:
    gene_id = event.get("gene_id", "?")
    blast_radius = event.get("blast_radius", {})
    outcome = event.get("outcome") or {}
    files = blast_radius.get("files", 0)
    status = outcome.get("status", "?")
    if status == "failed":
        return f"基因 {gene_id} 执行失败——是策略问题还是环境问题？"
    if files == 0:
        return f"基因 {gene_id} 零文件变更——究竟是预防性修复，还是空操作？"
    if files > 10:
        return f"基因 {gene_id} 爆炸半径 {files} 个文件——风险控制在哪里？"
    score = outcome.get("score")
    if isinstance(score, (int, float)) and score < 50:
        return f"基因 {gene_id} 得分仅 {score}——真正解决问题了吗？"
    return f"基因 {gene_id} 完成——值得加固吗？"


def _critic_verbose(event: dict[str, Any]) -> str:
    gene_id = event.get("gene_id", "?")
    mutation = event.get("mutation") or {}
    signals = event.get("signals", [])
    blast_radius = event.get("blast_radius", {})
    outcome = event.get("outcome") or {}
    risk = _risk_label(mutation)
    signal_text = _signal_summary(signals)
    blast = _blast_text(blast_radius)
    lines = [
        "=== Critic 评述 ===",
        f"基因: {gene_id} | 风险: {risk} | {_outcome_label(outcome)}",
        f"触发: {signal_text}",
        f"范围: {blast}",
    ]
    files = blast_radius.get("files", 0)
    if outcome.get("status") == "failed":
        lines.append("质疑: 为何预检未能拦截？信号选择是否精准？")
    elif files > 10:
        lines.append(f"质疑: {files} 个文件，爆炸半径过大。建议分拆为更小的变异单元。")
    elif files == 0:
        lines.append("质疑: 零文件变更。请确认不是配置修改或缓存清除。")
    else:
        lines.append("质疑: 表面看起来正常——但需要回归测试验证未引入回归。")
    lines.append("建议: 加固前请执行 canary 验证 + 爆炸半径审查。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_SHORT_GENERATORS = {
    "pragmatist": _pragmatist_short,
    "explorer": _explorer_short,
    "critic": _critic_short,
}

_VERBOSE_GENERATORS = {
    "pragmatist": _pragmatist_verbose,
    "explorer": _explorer_verbose,
    "critic": _critic_verbose,
}


def generate_commentary(
    event: dict[str, Any],
    *,
    persona: str = "pragmatist",
    verbose: bool = False,
) -> str:
    """Generate persona-styled commentary for an evolution event.

    Args:
        event: Evolution event dict (gene_id, signals, mutation, blast_radius, outcome).
        persona: One of ``pragmatist``, ``explorer``, ``critic``.
        verbose: Return detailed multi-line commentary instead of short (< 140 char).
    """
    if persona not in _PERSONAS:
        persona = "pragmatist"
    if verbose:
        return _VERBOSE_GENERATORS[persona](event)
    return _SHORT_GENERATORS[persona](event)


def generate_all_commentaries(
    event: dict[str, Any],
    *,
    verbose: bool = False,
) -> dict[str, str]:
    """Return all three persona commentaries for an event."""
    return {
        persona: generate_commentary(event, persona=persona, verbose=verbose)
        for persona in _PERSONAS
    }


def commentary_timeline(
    events: list[dict[str, Any]],
    *,
    persona: str = "pragmatist",
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """Generate commentary for a timeline of events."""
    results: list[dict[str, Any]] = []
    for evt in events:
        results.append(
            {
                "event_id": evt.get("id"),
                "gene_id": evt.get("gene_id"),
                "timestamp": evt.get("timestamp"),
                "persona": persona,
                "commentary": generate_commentary(evt, persona=persona, verbose=verbose),
            }
        )
    return results


def generate_commentary_for_latest_run(
    *,
    verbose: bool = False,
) -> dict[str, Any]:
    """Generate all three commentaries for the most recent solidify event."""
    try:
        from evolver.gep.asset_store import read_all_events

        events = read_all_events()
        solidify_events = [e for e in events if e.get("type") == "solidify"]
        if not solidify_events:
            return {"error": "no_solidify_events", "commentaries": {}}

        latest = solidify_events[-1]
        return {
            "event_id": latest.get("id"),
            "gene_id": latest.get("gene_id"),
            "timestamp": latest.get("timestamp"),
            "commentaries": generate_all_commentaries(latest, verbose=verbose),
        }
    except Exception as exc:
        return {"error": str(exc), "commentaries": {}}
