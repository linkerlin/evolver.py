"""Stable FNV-1a hashing shared across GEP modules.

Equivalent to ``evolver/src/gep/hash.js``.
"""

from __future__ import annotations


def stable_hash(value: object) -> str:
    """FNV-1a 32-bit hash as 8-char lowercase hex (Node ``stableHash``)."""
    s = str(value or "")
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return f"{h:08x}"


__all__ = ["stable_hash"]
