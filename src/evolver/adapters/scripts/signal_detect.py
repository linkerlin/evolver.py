"""Signal-detect hook — lightweight signal detection on file edit events.

Equivalent to ``evolver/src/adapters/scripts/evolver-signal-detect.js`` (98 lines).

Input: stdin JSON (edit event). Output: stdout JSON with ``additional_context``.

Applies **context-aware stratification** (refactor 3d7804f, 2026-05-25):
comment/code-structure lines are stripped before keyword matching to reduce
false positives. Supports Claude Code's PostToolUse payload shape
(``tool_input`` / ``tool_response`` nesting) and raw top-level shapes.
"""

from __future__ import annotations

import json
import re
import sys

# Signal keyword catalogue (mirrors evolver-signal-detect.js).
SIGNAL_KEYWORDS: dict[str, list[str]] = {
    "perf_bottleneck": [
        "timeout",
        "slow",
        "latency",
        "bottleneck",
        "oom",
        "out of memory",
        "performance",
    ],
    "capability_gap": [
        "not supported",
        "unsupported",
        "not implemented",
        "missing feature",
        "not available",
    ],
    "log_error": [
        "error:",
        "exception:",
        "typeerror",
        "referenceerror",
        "syntaxerror",
        "failed",
    ],
    "user_feature_request": [
        "add feature",
        "implement",
        "new function",
        "new module",
        "please add",
    ],
    "recurring_error": [
        "same error",
        "still failing",
        "not fixed",
        "keeps failing",
        "repeatedly",
    ],
    "deployment_issue": [
        "deploy failed",
        "build failed",
        "ci failed",
        "pipeline",
        "rollback",
    ],
    "test_failure": [
        "test failed",
        "test failure",
        "assertion",
        "expect(",
        "assert.",
    ],
}

# Lines that look like comments or code structure — skipped during stratification
# to avoid false-positive keyword hits inside code (e.g. a variable named
# ``failed_count`` should not trigger ``log_error``).
_STRUCTURE_PREFIXES = ("//", "#", "*", "{", "[", "}", "]", "/*", '"""', "'''")
_MULTILINGUAL_ERROR = re.compile(
    r"(?:错误|失败|异常|エラー|失敗|오류|실패)", re.IGNORECASE
)


def stratify_content(text: str) -> str:
    """Strip comment/code-structure lines, keeping document-like text only.

    Reduces false positives from variable names, imports, and JSON keys
    (refactor 3d7804f).
    """
    kept: list[str] = []
    for line in text.split("\n"):
        trimmed = line.strip()
        if any(trimmed.startswith(p) for p in _STRUCTURE_PREFIXES):
            continue
        kept.append(line)
    return "\n".join(kept)


def detect_signals(text: str | None) -> list[str]:
    """Return a deduplicated list of signal tags found in *text*."""
    if not text or not isinstance(text, str):
        return []
    stratified = stratify_content(text)
    lower = stratified.lower()
    found: list[str] = []
    for signal, keywords in SIGNAL_KEYWORDS.items():
        for kw in keywords:
            if kw in lower:
                found.append(signal)
                break
    # Multilingual fallback (English keywords miss CJK/Japanese/Korean errors).
    if not found and _MULTILINGUAL_ERROR.search(stratified):
        found.append("log_error")
    # Deduplicate preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for s in found:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


def _extract_content(input_data: dict[str, object]) -> tuple[str, str]:
    """Extract (content, file_path) from a hook payload (multiple shapes)."""
    ti = input_data.get("tool_input")
    if not isinstance(ti, dict):
        ti = {}
    tr = input_data.get("tool_response")
    if not isinstance(tr, dict):
        tr = {}

    content = (
        ti.get("content")
        or ti.get("new_string")
        or ti.get("file_content")
        or input_data.get("content")
        or input_data.get("file_content")
        or input_data.get("diff")
        or ""
    )
    file_path = (
        ti.get("file_path")
        or tr.get("filePath")
        or input_data.get("path")
        or input_data.get("file_path")
        or ""
    )
    return str(content), str(file_path)


def build_signal_output(input_data: dict[str, object]) -> dict[str, str]:
    """Build the signal-detect JSON output from a parsed input payload."""
    content, file_path = _extract_content(input_data)
    signals = detect_signals(content)
    if not signals:
        return {}
    ctx = (
        f"[Evolution Signal] Detected: [{', '.join(signals)}] in "
        f"{file_path or 'edited file'}. Consider recording this outcome."
    )
    return {"additional_context": ctx, "additionalContext": ctx}


def main() -> None:
    try:
        raw = sys.stdin.read().strip()
        input_data = json.loads(raw) if raw else {}
        if not isinstance(input_data, dict):
            input_data = {}
    except (json.JSONDecodeError, OSError):
        input_data = {}

    try:
        output = build_signal_output(input_data)
    except Exception:
        output = {}
    sys.stdout.write(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
