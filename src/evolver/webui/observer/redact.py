"""Sensitive information redaction for WebUI display."""

from __future__ import annotations

import re

# Patterns for common secrets
_PATTERNS = [
    (re.compile(r"bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE), "Bearer <REDACTED>"),
    (re.compile(r"api[_-]?key[:\s=]+[a-zA-Z0-9_\-\.]{16,}", re.IGNORECASE), "API_KEY=<REDACTED>"),
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "<REDACTED>"),
    (re.compile(r"password[:\s=]+\S+", re.IGNORECASE), "password=<REDACTED>"),
    (re.compile(r"secret[:\s=]+\S+", re.IGNORECASE), "secret=<REDACTED>"),
    (re.compile(r"token[:\s=]+[a-zA-Z0-9_\-\.]{16,}", re.IGNORECASE), "token=<REDACTED>"),
]


def redact_text(text: str) -> str:
    """Replace likely secrets with ``<REDACTED>``."""
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text
