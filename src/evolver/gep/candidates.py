"""Capability candidates — expandSignals + extractCapabilityCandidates.

Equivalent to ``evolver/src/gep/candidates.js`` (behaviour port from v1.91.2
tests + live module probes). Derives structured ``problem:*`` / ``action:*``
learning tags and surfaceable CapabilityCandidate objects for the evolve
prompt.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from evolver.gep.hash_utils import stable_hash

# Signals that always mint a signal-sourced capability candidate (whitelist).
_SIGNAL_TITLES: dict[str, str] = {
    "log_error": "Repair recurring runtime errors",
    "perf_bottleneck": "Resolve performance bottleneck",
    "protocol_drift": "Prevent protocol drift and enforce auditable outputs",
    "capability_gap": "Fill capability gap",
    "user_feature_request": "Implement user-requested feature",
    "external_opportunity": "Evaluate external A2A asset for local adoption",
    "stable_success_plateau": "Explore new strategies during stability plateau",
}

# Preferred problem tag when a failed-capsule group expands to several.
_PROBLEM_PRIORITY: list[str] = [
    "problem:performance",
    "problem:protocol",
    "problem:stagnation",
    "problem:capability",
    "problem:reliability",
]

_FAILED_TITLES: dict[str, str] = {
    "problem:performance": "Resolve recurring performance regressions",
    "problem:protocol": "Prevent recurring protocol and validation regressions",
    "problem:stagnation": "Break repeated stagnation loops with a new strategy",
    "problem:capability": "Learn from recurring failed evolution paths",
    "problem:reliability": "Repair recurring reliability failures",
}

_DEFAULT_SHAPE = {
    "input": "Recent session transcript + memory snippets + user instructions",
    "output": "A safe, auditable evolution patch guided by GEP assets",
    "invariants": "Protocol order, small reversible patches, validation, append-only events",
    "failure_points": (
        "Missing signals, over-broad changes, skipped validation, missing knowledge solidification"
    ),
}

_RE_RELIABILITY = re.compile(r"(error|exception|failed|unstable|log_error|runtime|429)", re.I)
_RE_PROTOCOL = re.compile(r"(protocol|prompt|audit|gep|schema|drift)", re.I)
_RE_PERF = re.compile(r"(perf|performance|bottleneck|latency|slow|throughput)", re.I)
_RE_CAPABILITY = re.compile(
    r"(feature|capability_gap|user_feature_request|external_opportunity|"
    r"stagnation recommendation)",
    re.I,
)
_RE_STAGNATION = re.compile(r"(plateau|stagnation)", re.I)
_RE_VALIDATION = re.compile(r"(validation|constraint)", re.I)


def _push_unique(out: list[str], value: str | None) -> None:
    if not value:
        return
    text = str(value).strip()
    if text and text not in out:
        out.append(text)


def expand_signals(signals: Any, text: str = "") -> list[str]:
    """Derive structured learning tags from weak signals + free text.

    Preserves original signal strings, adds colon-prefix fragments, and
    synthesises ``problem:*`` / ``action:*`` / ``area:*`` / ``risk:*`` tags.
    """
    raw = list(signals) if isinstance(signals, list) else []
    as_str = [str(s) for s in raw]
    out: list[str] = []
    for sig in as_str:
        _push_unique(out, sig)
        if ":" in sig:
            prefix = sig.split(":", 1)[0]
            if prefix and prefix != sig:
                _push_unique(out, prefix)

    hay = (" ".join(as_str) + " " + str(text or "")).lower()

    if _RE_RELIABILITY.search(hay):
        _push_unique(out, "problem:reliability")
        _push_unique(out, "action:repair")
    if _RE_PROTOCOL.search(hay):
        _push_unique(out, "problem:protocol")
        _push_unique(out, "action:optimize")
        _push_unique(out, "area:prompt")
    if _RE_PERF.search(hay):
        _push_unique(out, "problem:performance")
        _push_unique(out, "action:optimize")
    if _RE_CAPABILITY.search(hay):
        _push_unique(out, "problem:capability")
        _push_unique(out, "action:innovate")
    if _RE_STAGNATION.search(hay):
        _push_unique(out, "problem:stagnation")
        _push_unique(out, "action:innovate")
    if _RE_VALIDATION.search(hay):
        _push_unique(out, "risk:validation")

    return out


def _iso_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _shape(
    *,
    title: str,
    signals: list[str],
    evidence: str,
) -> dict[str, str]:
    params = "Signals: " + (", ".join(signals) if signals else "")
    return {
        "title": title,
        "input": _DEFAULT_SHAPE["input"],
        "output": _DEFAULT_SHAPE["output"],
        "invariants": _DEFAULT_SHAPE["invariants"],
        "params": params.rstrip() if signals else "Signals:",
        "failure_points": _DEFAULT_SHAPE["failure_points"],
        "evidence": evidence,
    }


def _primary_problem(tags: list[str]) -> str | None:
    tag_set = set(tags)
    for problem in _PROBLEM_PRIORITY:
        if problem in tag_set:
            return problem
    return None


def _failed_capsule_candidates(
    recent_failed: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for cap in recent_failed:
        if not isinstance(cap, dict):
            continue
        outcome = cap.get("outcome") if isinstance(cap.get("outcome"), dict) else {}
        status = outcome.get("status")
        # Missing outcome counts as failed; explicit non-failed statuses are skipped.
        if status is not None and status != "failed":
            continue

        trigger = cap.get("trigger") if isinstance(cap.get("trigger"), list) else []
        reason = str(cap.get("failure_reason") or cap.get("reason") or "")
        hay_parts = [str(t) for t in trigger if t] + ([reason] if reason else [])
        tags = expand_signals(hay_parts, reason)
        problem = _primary_problem(tags)
        if not problem:
            continue
        bucket = groups.setdefault(
            problem,
            {"count": 0, "tags": [], "reasons": [], "triggers": [], "signals": []},
        )
        bucket["count"] += 1
        for t in tags:
            _push_unique(bucket["tags"], t)
        if reason:
            bucket["reasons"].append(reason)
        for t in trigger:
            if t:
                _push_unique(bucket["triggers"], str(t))
                _push_unique(bucket["signals"], str(t))

    out: list[dict[str, Any]] = []
    for problem, bucket in groups.items():
        if bucket["count"] < 2:
            continue
        title = _FAILED_TITLES.get(problem, "Learn from recurring failed evolution paths")
        reasons: list[str] = bucket["reasons"]
        latest = reasons[0] if reasons else ""
        evidence = (
            f"Observed {bucket['count']} recent failed evolutions with similar learning tags."
            + (f" Latest reason: {latest}" if latest else "")
        )
        signals = list(bucket["signals"])
        cand = {
            "type": "CapabilityCandidate",
            "id": f"cand_{stable_hash(f'failed:{problem}')}",
            "title": title,
            "source": "failed_capsules",
            "created_at": _iso_now(),
            "signals": signals,
            "tags": list(bucket["tags"]),
            "shape": _shape(title=title, signals=signals, evidence=evidence),
        }
        out.append(cand)
    return out


def _signal_candidates(signals: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sig in signals:
        if sig not in _SIGNAL_TITLES:
            continue
        title = _SIGNAL_TITLES[sig]
        tags = expand_signals([sig], "")
        cand = {
            "type": "CapabilityCandidate",
            "id": f"cand_{stable_hash(sig)}",
            "title": title,
            "source": "signals",
            "created_at": _iso_now(),
            "signals": [sig],
            "tags": tags,
            "shape": _shape(
                title=title,
                signals=[sig],
                evidence=f"Signal present: {sig}",
            ),
        }
        out.append(cand)
    return out


def extract_capability_candidates(ctx: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Build CapabilityCandidate list from signals + recent failed capsules.

    *ctx* keys (Node camelCase + snake_case accepted):
    ``signals``, ``recentFailedCapsules`` / ``recent_failed_capsules``,
    ``recentSessionTranscript`` / ``recent_session_transcript`` (reserved).
    """
    ctx = ctx or {}
    raw_signals = ctx.get("signals") or []
    signals = [str(s) for s in raw_signals] if isinstance(raw_signals, list) else []

    failed = ctx.get("recentFailedCapsules") or ctx.get("recent_failed_capsules") or []
    if not isinstance(failed, list):
        failed = []

    candidates = _signal_candidates(signals) + _failed_capsule_candidates(failed)

    # Deduplicate by id (stable).
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for cand in candidates:
        cid = cand.get("id")
        if not cid or cid in seen:
            continue
        seen.add(str(cid))
        unique.append(cand)
    return unique


def render_candidates_preview(
    candidates: list[dict[str, Any]] | None,
    max_chars: int = 4000,
) -> str:
    """Render a compact multi-line preview for the GEP prompt."""
    items = candidates if isinstance(candidates, list) else []
    lines: list[str] = []
    for cand in items:
        if not isinstance(cand, dict):
            continue
        shape = cand.get("shape") if isinstance(cand.get("shape"), dict) else {}
        lines.append(f"- {cand.get('id')}: {cand.get('title')}")
        lines.append(f"  - input: {shape.get('input') or ''}")
        lines.append(f"  - output: {shape.get('output') or ''}")
        lines.append(f"  - invariants: {shape.get('invariants') or ''}")
        lines.append(f"  - params: {shape.get('params') or ''}")
        lines.append(f"  - failure_points: {shape.get('failure_points') or ''}")
        if shape.get("evidence"):
            lines.append(f"  - evidence: {shape.get('evidence')}")
    text = "\n".join(lines)
    if max_chars and len(text) > max_chars:
        return text[: max(0, max_chars - 1)] + "…"
    return text


__all__ = [
    "expand_signals",
    "extract_capability_candidates",
    "render_candidates_preview",
]
