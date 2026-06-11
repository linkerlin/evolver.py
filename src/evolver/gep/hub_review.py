"""Hub review engine — lightweight peer-review & quality gate for Hub assets.

Evaluates a Hub asset (service listing, PR, skill, patch) against a rubric
and produces a structured review verdict.

Equivalent to Node's ``evolver/src/gep/hubReview.js``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class Verdict(Enum):
    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"


@dataclass
class ReviewComment:
    severity: str  # info | warning | error | suggestion
    message: str
    line: int | None = None
    file: str | None = None


@dataclass
class ReviewResult:
    verdict: Verdict
    score: float  # 0.0 – 100.0
    comments: list[ReviewComment] = field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# Rubric
# ---------------------------------------------------------------------------


def review_service_listing(data: dict[str, Any]) -> ReviewResult:
    """Review an ATP service listing and return a structured result."""
    comments: list[ReviewComment] = []
    score = 100.0

    title = str(data.get("title", "")).strip()
    description = str(data.get("description", "")).strip()
    price = data.get("price_per_task")
    capabilities = data.get("capabilities", [])
    mode = data.get("execution_mode", "")

    if len(title) < 5:
        comments.append(ReviewComment("error", "Title too short (minimum 5 characters)."))
        score -= 20
    if len(description) < 20:
        comments.append(ReviewComment("error", "Description too short (minimum 20 characters)."))
        score -= 20
    if not capabilities:
        comments.append(ReviewComment("warning", "No capabilities declared."))
        score -= 10
    if mode not in {"sync", "async", "batch"}:
        comments.append(ReviewComment("warning", f"Unknown execution_mode '{mode}'."))
        score -= 5
    if price is None:
        comments.append(ReviewComment("warning", "Missing price_per_task."))
        score -= 10
    elif not isinstance(price, (int, float)) or price < 0:
        comments.append(ReviewComment("error", "price_per_task must be a non-negative number."))
        score -= 15

    verdict = Verdict.APPROVE if score >= 80 else Verdict.REVISE if score >= 40 else Verdict.REJECT

    summary = f"Score {score:.1f}/100 — {len(comments)} comment(s)."
    logger.info("[HubReview] service listing reviewed: %s", summary)
    return ReviewResult(verdict=verdict, score=score, comments=comments, summary=summary)


def review_patch(diff_text: str, changed_files: list[str]) -> ReviewResult:
    """Lightweight static review of a code diff."""
    comments: list[ReviewComment] = []
    score = 100.0

    if not diff_text:
        comments.append(ReviewComment("error", "Empty diff."))
        return ReviewResult(
            verdict=Verdict.REJECT, score=0.0, comments=comments, summary="Empty diff."
        )

    # Basic heuristics
    if "TODO" in diff_text or "FIXME" in diff_text:
        comments.append(ReviewComment("warning", "Diff contains TODO/FIXME markers."))
        score -= 5

    if diff_text.count("\n") > 500:
        comments.append(
            ReviewComment("warning", "Diff exceeds 500 lines — consider breaking into smaller PRs.")
        )
        score -= 10

    # Check for suspicious patterns
    suspicious = ["eval(", "os.system", "subprocess.call", "exec(", "compile("]
    for pat in suspicious:
        if pat in diff_text:
            comments.append(ReviewComment("error", f"Suspicious pattern '{pat}' detected in diff."))
            score -= 65

    verdict = Verdict.APPROVE if score >= 80 else Verdict.REVISE if score >= 40 else Verdict.REJECT

    summary = f"Score {score:.1f}/100 — {len(comments)} comment(s) on {len(changed_files)} file(s)."
    logger.info("[HubReview] patch reviewed: %s", summary)
    return ReviewResult(verdict=verdict, score=score, comments=comments, summary=summary)
