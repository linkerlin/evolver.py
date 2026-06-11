"""LLM review gate — block solidify until a diff passes LLM review.

Equivalent to Node's ``evolver/src/gep/llmReview.js``.

Before solidify, sends the git diff + gene intent + safety constraints
to an LLM (via the local Proxy ``/v1/messages``). The LLM returns:
* ``approved`` (bool)
* ``confidence`` (0-1)
* ``concerns`` (list of strings)

If ``approved=False`` or ``confidence < 0.7``, solidify is blocked and
the mutation enters "review mode" (logged but not applied).

Design notes
------------
* Respects ``enable_llm_review`` feature flag.
* Results are persisted to ``memory/llm-reviews.jsonl``.
* Timeout: 10s for diffs < 100 lines, 30s for larger diffs.
* On LLM failure, defaults to ``approved=False`` with a warning.
* The prompt is deterministic — same diff → same request.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evolver.gep.feature_flags import is_enabled
from evolver.gep.paths import get_workspace_root
from evolver.gep.sanitize import full_leak_check

logger = logging.getLogger(__name__)

# Config
MIN_CONFIDENCE = 0.7
REVIEW_LOG_PATH = Path("memory") / "llm-reviews.jsonl"

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class LLMReviewResult:
    approved: bool
    confidence: float
    concerns: list[str] = field(default_factory=list)
    raw_response: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "llm_review",
            "timestamp": time.time(),
            "approved": self.approved,
            "confidence": self.confidence,
            "concerns": self.concerns,
            "latency_ms": self.latency_ms,
        }


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def _build_prompt(diff_text: str, gene_summary: str, constraints: list[str] | None = None) -> str:
    """Build a deterministic review prompt."""
    constraints = constraints or [
        "1. Do not approve changes that modify secrets, API keys, or credentials.",
        "2. Do not approve changes that delete critical files (.env, pyproject.toml, etc.).",
        "3. Do not approve changes that introduce potential security vulnerabilities.",
        "4. Prefer small, focused changes over large sweeping refactors.",
        "5. Ensure test files are included if logic changes.",
    ]
    lines = [
        (
            "You are a senior code reviewer. Review the following git diff "
            "and decide whether it should be approved."
        ),
        "",
        "## Gene Summary",
        gene_summary or "(no summary provided)",
        "",
        "## Constraints",
        *[f"- {c}" for c in constraints],
        "",
        "## Diff",
        "```diff",
        diff_text,
        "```",
        "",
        "Respond with a JSON object in this exact format (no markdown, no prose):",
        '{"approved": true|false, "confidence": 0.0-1.0, "concerns": ["concern 1", "concern 2"]}',
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, timeout: float = 10.0) -> str:
    """Call the local Proxy LLM endpoint.

    Returns the raw text response, or raises on failure.
    """
    try:
        import httpx

        resp = httpx.post(
            "http://127.0.0.1:19820/v1/messages",
            json={
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        # Extract content from Anthropic-style response
        content = data.get("content", "")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                return str(first.get("text", ""))
        return str(content)
    except Exception as exc:
        raise RuntimeError(f"LLM call failed: {exc}") from exc


def _parse_review_response(text: str) -> LLMReviewResult:
    """Parse the LLM response into :class:`LLMReviewResult`."""
    # Try to extract JSON from the response
    text = text.strip()
    # Handle markdown code blocks
    if text.startswith("```"):
        text = text.split("```", 2)[1] if "```" in text[3:] else text
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fallback: assume not approved if unparseable
        return LLMReviewResult(
            approved=False,
            confidence=0.0,
            concerns=[f"Unparseable LLM response: {text[:200]}"],
            raw_response=text,
        )

    approved = bool(data.get("approved", False))
    confidence = float(data.get("confidence", 0.0))
    concerns = list(data.get("concerns", []))
    if not isinstance(concerns, list):
        concerns = [str(concerns)]
    return LLMReviewResult(
        approved=approved,
        confidence=confidence,
        concerns=concerns,
        raw_response=text,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _log_review(result: LLMReviewResult) -> None:
    path = get_workspace_root() / REVIEW_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.debug("[LLMReview] Failed to log review: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def review_diff(
    diff_text: str,
    *,
    gene_summary: str = "",
    constraints: list[str] | None = None,
    timeout: float | None = None,
) -> LLMReviewResult:
    """Review *diff_text* via LLM.

    Returns :class:`LLMReviewResult`.
    """
    if not is_enabled("enable_llm_review"):
        # When disabled, auto-approve with low confidence so solidify can proceed
        return LLMReviewResult(approved=True, confidence=0.5, concerns=["LLM review disabled"])

    # Leak check before sending to LLM
    leak = full_leak_check(diff_text)
    if not leak["safe"]:
        return LLMReviewResult(
            approved=False,
            confidence=0.0,
            concerns=["Secret leak detected — refusing to send to LLM"]
            + leak.get("pattern_leaks", []),
        )

    t0 = time.time()
    effective_timeout = timeout or (10.0 if len(diff_text.splitlines()) < 100 else 30.0)

    prompt = _build_prompt(diff_text, gene_summary, constraints)
    try:
        raw = _call_llm(prompt, timeout=effective_timeout)
        result = _parse_review_response(raw)
    except Exception as exc:
        logger.warning("[LLMReview] LLM call failed: %s", exc)
        result = LLMReviewResult(
            approved=False,
            confidence=0.0,
            concerns=[f"LLM call failed: {exc}"],
        )

    result.latency_ms = (time.time() - t0) * 1000
    _log_review(result)
    return result


def is_approved(result: LLMReviewResult, min_confidence: float = MIN_CONFIDENCE) -> bool:
    """Return ``True`` if *result* is approved with sufficient confidence."""
    return result.approved and result.confidence >= min_confidence
