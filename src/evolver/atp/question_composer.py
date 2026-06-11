"""ATP question composer — generate human-readable buyer questions.

Equivalent to ``evolver/src/atp/questionComposer.js``.
Maps capability/signal inputs to natural-language buyer questions.
"""

from __future__ import annotations

import re

# Templates by capability key
templates: dict[str, list[str]] = {
    "code_evolution": [
        "Improve the following code pattern: {signal}",
        "Refactor this implementation to be more robust: {signal}",
    ],
    "performance": [
        "Optimize performance for: {signal}",
        "Why is this slow and how can we fix it? {signal}",
    ],
    "debugging": [
        "Debug this issue: {signal}",
        "Find the root cause of: {signal}",
    ],
    "testing": [
        "Write tests covering: {signal}",
        "Improve test coverage for: {signal}",
    ],
    "documentation": [
        "Document how this works: {signal}",
        "Add clear docs for: {signal}",
    ],
    "refactoring": [
        "Refactor this module: {signal}",
        "Restructure this code: {signal}",
    ],
    "security": [
        "Audit security of: {signal}",
        "Fix security issue: {signal}",
    ],
    "data_analysis": [
        "Analyze this data pattern: {signal}",
        "Derive insights from: {signal}",
    ],
    "architecture": [
        "Design a better architecture for: {signal}",
        "Propose structure for: {signal}",
    ],
    "deployment": [
        "Fix deployment failure: {signal}",
        "Improve CI/CD for: {signal}",
    ],
    "general": [
        "Help with: {signal}",
        "Address this need: {signal}",
    ],
}


def _normalize(key: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", key.lower().strip())


def _hash_for(seed: str, limit: int) -> int:
    """Deterministic hash for template selection."""
    h = 0
    for ch in seed:
        h = ((h << 5) - h) + ord(ch)
        h &= 0xFFFFFFFF
    return h % limit


def compose(
    capabilities: list[str],
    signal: str = "",
    max_length: int = 240,
) -> str:
    """Compose a buyer question from capabilities and signal."""
    key = _normalize(capabilities[0]) if capabilities else "general"
    candidates = templates.get(key, templates["general"])
    idx = _hash_for(signal or key, len(candidates))
    question = candidates[idx].format(signal=signal or key)
    if len(question) > max_length:
        question = question[: max_length - 3] + "..."
    return question


def _pick_template(key: str, seed: str) -> str:
    candidates = templates.get(key, templates["general"])
    idx = _hash_for(seed, len(candidates))
    return candidates[idx]
