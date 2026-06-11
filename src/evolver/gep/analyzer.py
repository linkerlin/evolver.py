"""Fault analyzer — structured root-cause analysis for failures.

Given a failure (exception, test result, CI log), produces a diagnosis
with confidence, probable cause, and recommended fix.

Equivalent to Node's ``evolver/src/gep/analyzer.js``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CauseCategory(Enum):
    ENVIRONMENT = "environment"
    CODE = "code"
    TEST = "test"
    INFRASTRUCTURE = "infrastructure"
    NETWORK = "network"
    UNKNOWN = "unknown"


@dataclass
class Diagnosis:
    confidence: float  # 0.0 – 1.0
    category: CauseCategory
    cause: str
    recommendation: str
    relevant_lines: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Heuristic matchers
# ---------------------------------------------------------------------------


def _match_module_not_found(text: str) -> Diagnosis | None:
    m = re.search(r"ModuleNotFoundError: No module named '([^']+)'", text)
    if m:
        mod = m.group(1)
        return Diagnosis(
            confidence=0.95,
            category=CauseCategory.ENVIRONMENT,
            cause=f"Missing Python dependency: {mod}",
            recommendation=f"Install the missing package (e.g. `uv pip install {mod}`) or add it to pyproject.toml dependencies.",
            relevant_lines=[m.group(0)],
        )
    return None


def _match_assertion(text: str) -> Diagnosis | None:
    if "AssertionError" in text or "assert " in text:
        lines = [ln for ln in text.splitlines() if "assert" in ln.lower() or "AssertionError" in ln]
        return Diagnosis(
            confidence=0.90,
            category=CauseCategory.TEST,
            cause="Test assertion failed.",
            recommendation="Check the expected vs actual values; if logic is correct, update the test expectation.",
            relevant_lines=lines[:3],
        )
    return None


def _match_syntax(text: str) -> Diagnosis | None:
    if "SyntaxError" in text or "IndentationError" in text:
        lines = [ln for ln in text.splitlines() if "SyntaxError" in ln or "IndentationError" in ln or "^" in ln]
        return Diagnosis(
            confidence=0.95,
            category=CauseCategory.CODE,
            cause="Python syntax or indentation error.",
            recommendation="Review the indicated line for invalid syntax or mismatched indentation.",
            relevant_lines=lines[:3],
        )
    return None


def _match_timeout(text: str) -> Diagnosis | None:
    low = text.lower()
    if "timeout" in low or "timed out" in low:
        return Diagnosis(
            confidence=0.85,
            category=CauseCategory.INFRASTRUCTURE,
            cause="Operation timed out.",
            recommendation="Increase timeout, reduce workload, or investigate resource contention.",
        )
    return None


def _match_connection(text: str) -> Diagnosis | None:
    if any(k in text for k in ("Connection refused", "Connection reset", "Name or service not known", "getaddrinfo")):
        return Diagnosis(
            confidence=0.90,
            category=CauseCategory.NETWORK,
            cause="Network connectivity issue.",
            recommendation="Check DNS, firewall, or remote service availability.",
        )
    return None


def _match_permission(text: str) -> Diagnosis | None:
    if "Permission denied" in text or "Access is denied" in text:
        return Diagnosis(
            confidence=0.90,
            category=CauseCategory.ENVIRONMENT,
            cause="Permission denied.",
            recommendation="Run with appropriate privileges or fix file permissions.",
        )
    return None


def _match_import_cycle(text: str) -> Diagnosis | None:
    if "ImportError" in text and "circular" in text.lower():
        return Diagnosis(
            confidence=0.90,
            category=CauseCategory.CODE,
            cause="Circular import detected.",
            recommendation="Refactor to break the cycle (e.g. lazy imports, protocol/interface separation).",
        )
    return None


def _match_key_error(text: str) -> Diagnosis | None:
    m = re.search(r"KeyError: '([^']+)'", text)
    if m:
        return Diagnosis(
            confidence=0.90,
            category=CauseCategory.CODE,
            cause=f"Missing dictionary key: {m.group(1)}",
            recommendation="Use dict.get() with a default or ensure the key is set before access.",
            relevant_lines=[m.group(0)],
        )
    return None


def _match_type_error(text: str) -> Diagnosis | None:
    if "TypeError" in text:
        lines = [ln for ln in text.splitlines() if "TypeError" in ln]
        return Diagnosis(
            confidence=0.80,
            category=CauseCategory.CODE,
            cause="Type mismatch or wrong argument signature.",
            recommendation="Review the call site and signature; add type hints for clarity.",
            relevant_lines=lines[:3],
        )
    return None


_MATCHERS = [
    _match_module_not_found,
    _match_assertion,
    _match_syntax,
    _match_timeout,
    _match_connection,
    _match_permission,
    _match_import_cycle,
    _match_key_error,
    _match_type_error,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze(failure_text: str, *, context: dict[str, Any] | None = None) -> Diagnosis:
    """Analyze a failure text and return a structured diagnosis.

    *context* is optional metadata (e.g. {"command": "pytest", "exit_code": 1}).
    """
    for matcher in _MATCHERS:
        diag = matcher(failure_text)
        if diag is not None:
            logger.info("[Analyzer] matched %s with confidence %.2f", diag.category.value, diag.confidence)
            return diag

    logger.info("[Analyzer] no heuristic matched — returning unknown")
    return Diagnosis(
        confidence=0.30,
        category=CauseCategory.UNKNOWN,
        cause="Could not automatically determine cause.",
        recommendation="Review the full log manually and consider adding a new heuristic to analyzer.py.",
    )
