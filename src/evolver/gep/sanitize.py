"""Redact secrets and detect leaks before publishing.

Equivalent to evolver/src/gep/sanitize.js.
"""

from __future__ import annotations

import os
import re
from typing import Sequence


_PATTERNS = {
    "bearer": re.compile(r"(?i)bearer\s+[a-z0-9_\-\.]{20,}"),
    "api_key": re.compile(r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"]?[a-z0-9_\-\.]{16,}"),
    "password": re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
    "secret": re.compile(r"(?i)(secret|token)\s*[:=]\s*['\"]?[a-z0-9_\-\.]{16,}"),
    "private_key": re.compile(r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
}


def redact_string(text: str) -> str:
    if not isinstance(text, str):
        return text
    out = text
    for name, pattern in _PATTERNS.items():
        out = pattern.sub(lambda m: f"<REDACTED:{name.upper()}>", out)
    return out


def scan_for_leaks(text: str | bytes) -> list[dict]:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    leaks: list[dict] = []
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


def detect_env_value_leaks(payload: dict | str) -> list[dict]:
    """Detect accidental inclusions of env variable values in payload."""
    text = json.dumps(payload) if isinstance(payload, dict) else payload
    leaks: list[dict] = []
    for key, value in os.environ.items():
        if not value or len(value) < 8:
            continue
        if value in text:
            leaks.append({"type": "env_value", "key": key, "length": len(value)})
    return leaks


def full_leak_check(payload: dict | str) -> dict:
    text = json.dumps(payload) if isinstance(payload, dict) else str(payload)
    return {
        "pattern_leaks": scan_for_leaks(text),
        "env_leaks": detect_env_value_leaks(payload),
        "safe": not scan_for_leaks(text) and not detect_env_value_leaks(payload),
    }


def sanitize_payload(payload: dict | str) -> str:
    """Best-effort sanitize a payload for publishing."""
    text = json.dumps(payload) if isinstance(payload, dict) else str(payload)
    return redact_string(text)


import json  # noqa: E402
