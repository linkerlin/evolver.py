"""Redact secrets and detect leaks before publishing.

Equivalent to evolver/src/gep/sanitize.js.

Security model (mirrors Node.js v1.89.5 #568):
  - Pattern-based redaction of bearer tokens, API keys, passwords, secrets,
    private keys.
  - Reverse leak scan: detect whether any *current env value* appears in the
    payload before publishing. Path/URL-shaped env values are skipped to avoid
    false positives (#568) — a ``PYTHONPATH`` containing a project path should
    not trigger a "leak" report.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

# --- Pattern catalogue --------------------------------------------------
# Mirrors the credential patterns in evolver/src/gep/sanitize.js, including
# the 11 redaction patterns contributed in PR #107 (voidborne-d).

_PATTERNS: dict[str, re.Pattern[str]] = {
    "bearer": re.compile(r"(?i)bearer\s+[a-z0-9_\-\.]{20,}"),
    "api_key": re.compile(r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"]?[a-z0-9_\-\.]{16,}"),
    "password": re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
    "secret": re.compile(r"(?i)(secret|token)\s*[:=]\s*['\"]?[a-z0-9_\-\.]{16,}"),
    "private_key": re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    "jwt": re.compile(r"(?i)eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]*"),
    "aws_access_key": re.compile(r"(?i)AKIA[0-9A-Z]{16}"),
    "github_token": re.compile(r"(?i)gh[pousr]_[A-Za-z0-9]{36,}"),
    "slack_token": re.compile(r"(?i)xox[baprs]-[A-Za-z0-9-]{10,}"),
    "connection_string": re.compile(
        r"(?i)(mongodb|postgres|postgresql|redis|amqp)://[^\s'\"]+:[^\s'\"]+@"
    ),
    "generic_high_entropy": re.compile(
        r"(?i)(authorization|auth|credential|access[_-]?token)\s*[:=]\s*['\"]?[a-z0-9_\-\.+/=]{32,}",
    ),
}

# Env value heuristics that indicate a *path* or *URL* rather than a secret.
# Reporting these as "leaks" produced false positives in the reverse scan
# (Node.js fix #568, 2026-06-11). We skip env values whose shape matches one
# of these so the leak check stays useful instead of noisy.

_PATH_LIKE = re.compile(
    r"^(?:[A-Za-z]:[\\/]|/|\.\.?[/\\]|~[/\\])"  # absolute or relative or ~ path
)
_URL_LIKE = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)
_FILE_EXT = re.compile(r"\.(py|js|ts|json|md|txt|toml|yaml|yml|lock|cfg|ini)$", re.IGNORECASE)


def _looks_like_path_or_url(value: str) -> bool:
    """Heuristic: does this env value look like a filesystem path or URL?

    Used to suppress false-positive "env value leaked" hits (#568). Real
    secrets (API keys, tokens) are opaque high-entropy strings, not paths.
    """
    if not value:
        return False
    if _URL_LIKE.match(value):
        return True
    if _PATH_LIKE.match(value):
        return True
    if _FILE_EXT.search(value):
        return True
    # Path-separator-heavy strings (e.g. "src;lib/site-packages")
    return value.count("/") >= 2 or value.count("\\") >= 2


def _redact_repl(label: str) -> Any:
    """Build a replacement callable that emits ``<REDACTED:LABEL>``."""

    def _repl(_match: re.Match[str]) -> str:
        return f"<REDACTED:{label}>"

    return _repl


# --- Public API ---------------------------------------------------------


def redact_string(text: str) -> str:
    """Replace known secret patterns in *text* with ``<REDACTED:TYPE>``."""
    if not isinstance(text, str):
        return text
    out = text
    for name, pattern in _PATTERNS.items():
        out = pattern.sub(_redact_repl(name.upper()), out)
    return out


def scan_for_leaks(text: str | bytes) -> list[dict[str, Any]]:
    """Scan *text* for credential patterns, returning a list of hit dicts."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    leaks: list[dict[str, Any]] = []
    for name, pattern in _PATTERNS.items():
        for match in pattern.finditer(text):
            leaks.append(
                {
                    "type": name,
                    "start": match.start(),
                    "end": match.end(),
                    "snippet": text[max(0, match.start() - 10) : match.end() + 10],
                }
            )
    return leaks


def detect_env_value_leaks(
    payload: dict[str, Any] | str,
    *,
    env: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Detect accidental inclusions of env variable values in *payload*.

    Path/URL-shaped values are skipped (#568) to avoid false positives.
    """
    text = json.dumps(payload) if isinstance(payload, dict) else payload
    source = env if env is not None else os.environ
    leaks: list[dict[str, Any]] = []
    for key, value in source.items():
        if not value or len(value) < 8:
            continue
        if _looks_like_path_or_url(value):
            continue
        if value in text:
            leaks.append({"type": "env_value", "key": key, "length": len(value)})
    return leaks


def full_leak_check(payload: dict[str, Any] | str) -> dict[str, Any]:
    """Run both pattern and env-value leak scans."""
    text = json.dumps(payload) if isinstance(payload, dict) else str(payload)
    pattern_leaks = scan_for_leaks(text)
    env_leaks = detect_env_value_leaks(payload)
    return {
        "pattern_leaks": pattern_leaks,
        "env_leaks": env_leaks,
        "safe": not pattern_leaks and not env_leaks,
    }


def sanitize_payload(payload: dict[str, Any] | str) -> str:
    """Best-effort sanitize a payload for publishing (redact known secrets)."""
    text = json.dumps(payload) if isinstance(payload, dict) else str(payload)
    return redact_string(text)
