"""Conversation sniffer — surface reusable capabilities from session transcripts.

Equivalent to ``evolver/src/gep/conversationSniffer.js``.

Scans conversation/session text for **capability candidates**: cases where a
reusable action (e.g. ``lark-cli docs +create``) **co-occurs locally** with a
success marker (e.g. "published successfully"). The output feeds the evolution
pipeline as ``conv_capability:*`` signals.

Three modes (``EVOLVER_CONV_SNIFF_ENABLED``):
  - ``off``    — no scanning, no signals.
  - ``shadow`` — scan and surface candidates, but inject NO signals (observability).
  - ``enforce`` — scan and inject ``conv_capability:*`` signals into the pipeline.

Design constraints (Bugbot #175):
  - Success + action must co-occur **locally** (within ``PROXIMITY_CHARS``).
  - Distant success must NOT pair with an unrelated/failed capability mention.
  - Negated markers ("not verified", "未成功") cancel the success.
  - Array segments scanned independently — no cross-boundary false proximity.
  - Cooldown prevents repeated sniffing within ``COOLDOWN_S``.
  - An empty sniff (no candidates) must NOT arm the cooldown.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Capability patterns
# ---------------------------------------------------------------------------

#: Each entry: (compiled_trigger_regex, canonical_capability_name).
#: The trigger regex matches the reusable *action* portion of a transcript.
_CAPABILITY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"lark[- ]?cli", re.IGNORECASE),
        "publish-feishu-doc",
    ),
]

# ---------------------------------------------------------------------------
# Success / negation markers
# ---------------------------------------------------------------------------

#: English success markers — must co-occur within PROXIMITY_CHARS of a trigger.
_SUCCESS_MARKERS_EN: list[str] = [
    "published successfully",
    "published ok",
    "published",
    "successfully",
    "verified",
    "passed",
    "completed",
    "done",
]

#: Chinese success markers.
_SUCCESS_MARKERS_ZH: list[str] = [
    "已发布",
    "验证通过",
    "发布成功",
    "成功",
]

#: Negation markers — cancel a success if they appear near the success token.
_NEGATION_MARKERS_EN: list[str] = [
    "not verified",
    "not successfully",
    "failed to publish",
    "did not publish",
    "not published",
    "errored",
    "failed",
]

_NEGATION_MARKERS_ZH: list[str] = [
    "未成功",
    "失败",
    "未发布",
]

#: Maximum character distance between a trigger and a success marker for them
#: to count as co-occurring. Distant pairs must not surface (Bugbot #175 High).
PROXIMITY_CHARS = 200

# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

VALID_MODES = ("off", "shadow", "enforce")
DEFAULT_MODE = "off"


def _resolve_mode() -> str:
    """Read the sniff mode from env at call time (not module-load)."""
    raw = os.environ.get("EVOLVER_CONV_SNIFF_ENABLED", DEFAULT_MODE).strip().lower()
    return raw if raw in VALID_MODES else DEFAULT_MODE


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

_COOLDOWN_S = 300.0  # 5 min between sniffs


def _state_path() -> Path:
    """Return the path to the sniffer state file in the evolution dir."""
    try:
        from evolver.gep.paths import get_evolution_dir  # noqa: PLC0415

        return get_evolution_dir() / "conversation_sniffer_state.json"
    except Exception:
        # Fallback to a user-level path.
        return Path.home() / ".evolver" / "conversation_sniffer_state.json"


def read_state() -> dict[str, Any]:
    """Read the persisted sniffer state."""
    path = _state_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"seen": {}, "last_sniff_ts": 0}


def _write_state(state: dict[str, Any]) -> None:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Core scanning
# ---------------------------------------------------------------------------


def _check_negation(text_segment: str) -> bool:
    """Return True if a negation marker is present in *text_segment*."""
    lower = text_segment.lower()
    if any(marker in lower for marker in _NEGATION_MARKERS_EN):
        return True
    return any(marker in text_segment for marker in _NEGATION_MARKERS_ZH)


def _has_success_marker(text_segment: str) -> bool:
    """Return True if a positive success marker is present (not negated)."""
    if _check_negation(text_segment):
        return False
    lower = text_segment.lower()
    if any(marker in lower for marker in _SUCCESS_MARKERS_EN):
        return True
    return any(marker in text_segment for marker in _SUCCESS_MARKERS_ZH)


def _scan_segment(segment: str) -> list[str]:
    """Scan a single text segment for capabilities with local success co-occurrence.

    Returns a list of canonical capability names (deduplicated).
    """
    if not segment or not segment.strip():
        return []

    found: list[str] = []
    seen: set[str] = set()
    for trigger_re, cap_name in _CAPABILITY_PATTERNS:
        for match in trigger_re.finditer(segment):
            # Check a proximity window around the trigger for a success marker.
            start = max(0, match.start() - PROXIMITY_CHARS)
            end = min(len(segment), match.end() + PROXIMITY_CHARS)
            window = segment[start:end]
            if _has_success_marker(window) and cap_name not in seen:
                seen.add(cap_name)
                found.append(cap_name)
    return found


def scan_corpus(corpus: str | list[str] | None) -> list[dict[str, str]]:
    """Scan conversation text (or array of segments) for capability candidates.

    Returns ``[{capability: <name>}, ...]``.

    Array segments are scanned **independently** — success in segment A must
    not pair with a capability in segment B (Bugbot #175 r2).
    """
    if not corpus:
        return []

    if isinstance(corpus, str):
        segments: list[str] = [corpus]
    elif isinstance(corpus, list):
        segments = [str(s) for s in corpus if s]
    else:
        return []

    found: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        for cap_name in _scan_segment(segment):
            if cap_name not in seen:
                seen.add(cap_name)
                found.append(cap_name)

    return [{"capability": name} for name in found]


def convert_to_signals(candidates: list[dict[str, str]]) -> list[str]:
    """Convert capability candidates to evolution signal tags.

    Prepends the umbrella ``conv_capability_candidate`` signal, then emits a
    per-capability ``conv_capability:<name>`` signal for each candidate.
    """
    if not candidates:
        return []
    signals = ["conv_capability_candidate"]
    for c in candidates:
        cap = c.get("capability", "")
        if cap:
            signals.append(f"conv_capability:{cap}")
    return signals


# ---------------------------------------------------------------------------
# Main entry — trySniff
# ---------------------------------------------------------------------------


def try_sniff(
    corpus: str | list[str] | None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Sniff a conversation corpus and return signals (mode-dependent).

    Returns ``{mode, signals, candidates}``.

    - ``off``: no scanning, empty signals.
    - ``shadow``: scan but inject no signals (candidates still returned).
    - ``enforce``: scan and inject signals (subject to cooldown).
    """
    mode = _resolve_mode()
    if mode == "off":
        return {"mode": "off", "signals": [], "candidates": []}

    current_state = state if state is not None else read_state()

    # Cooldown check (enforce mode only).
    if mode == "enforce":
        last_ts = current_state.get("last_sniff_ts", 0)
        in_cooldown = (
            isinstance(last_ts, (int, float))
            and last_ts > 0
            and time.time() - last_ts < _COOLDOWN_S
        )
        if in_cooldown:
            return {"mode": mode, "signals": [], "candidates": []}

    candidates = scan_corpus(corpus)

    # An empty sniff must NOT arm the cooldown (Bugbot #175 Medium).
    if not candidates:
        return {"mode": mode, "signals": [], "candidates": []}

    # Arm the cooldown (only when candidates were found).
    if mode == "enforce":
        current_state["last_sniff_ts"] = time.time()
        _write_state(current_state)

    signals = convert_to_signals(candidates) if mode == "enforce" else []
    return {"mode": mode, "signals": signals, "candidates": candidates}


__all__ = [
    "PROXIMITY_CHARS",
    "VALID_MODES",
    "convert_to_signals",
    "read_state",
    "scan_corpus",
    "try_sniff",
]
