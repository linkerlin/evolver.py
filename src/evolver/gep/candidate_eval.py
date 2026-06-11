"""Candidate evaluator — rank multiple mutations and pick the best.

Equivalent to Node's ``evolver/src/gep/candidateEval.js``.

Given a list of candidate mutations (diffs), scores each along
multiple axes and returns a ranked list. The top candidate can be
passed directly to :func:`solidify`.

Scoring axes
------------
* **Complexity** — lines changed / files touched (lower is better).
* **Risk** — blast radius + protected-path exposure (lower is better).
* **Test coverage** — presence of test files in the diff (higher is better).
* **Signal match** — cosine similarity to current signal vector (higher is better).
* **Novelty** — how different from recent attempts (higher is better).

Ranking
-------
Default strategy is **tournament**: pair-wise comparison using a
weighted composite score. Optional ``elo`` strategy maintains an
ELO rating for each candidate hash.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from evolver.gep.policy_check import check_policy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CandidateScore:
    candidate_id: str
    complexity: float = 0.0  # 0-1 (lower better)
    risk: float = 0.0  # 0-1 (lower better)
    test_coverage: float = 0.0  # 0-1 (higher better)
    signal_match: float = 0.0  # 0-1 (higher better)
    novelty: float = 0.0  # 0-1 (higher better)
    composite: float = 0.0  # 0-1 (higher better)


@dataclass
class Candidate:
    diff_text: str
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    score: CandidateScore | None = None

    @property
    def candidate_id(self) -> str:
        return hashlib.sha256(self.diff_text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _score_complexity(diff_text: str) -> float:
    """Return complexity score (0-1). Lower is better."""
    lines = diff_text.splitlines()
    changed_lines = sum(
        1 for line in lines if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )
    files = len([line for line in lines if line.startswith("diff --git")])
    # Normalize: 50 changed lines → 0.5, 10 files → 0.5
    line_score = min(1.0, changed_lines / 100.0)
    file_score = min(1.0, files / 20.0)
    return (line_score + file_score) / 2.0


def _score_risk(diff_text: str) -> float:
    """Return risk score (0-1). Lower is better."""
    report = check_policy(diff_text=diff_text, changed_files=[], untracked_files=[])
    if not report.ok:
        critical_count = sum(1 for v in report.violations if v.severity == "critical")
        return min(1.0, critical_count / 5.0)
    return 0.0


def _score_test_coverage(diff_text: str) -> float:
    """Return test coverage score (0-1). Higher is better."""
    # Check if diff touches test files
    test_files = 0
    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            if "/test" in line.lower() or line.endswith("_test.py") or line.endswith("_tests.py"):
                test_files += 1
    return min(1.0, test_files / 3.0)


def _score_signal_match(diff_text: str, signal_vector: dict[str, float] | None) -> float:
    """Return signal match score (0-1). Higher is better."""
    if not signal_vector:
        return 0.5
    # Simple keyword overlap
    text_lower = diff_text.lower()
    matches = sum(1 for kw in signal_vector if kw.lower() in text_lower)
    return min(1.0, matches / max(1, len(signal_vector)))


def _score_novelty(diff_text: str, recent_diffs: list[str]) -> float:
    """Return novelty score (0-1). Higher is better."""
    if not recent_diffs:
        return 1.0
    h = hashlib.sha256(diff_text.encode("utf-8")).digest()
    similarities: list[float] = []
    for recent in recent_diffs:
        h2 = hashlib.sha256(recent.encode("utf-8")).digest()
        # Simple Jaccard-ish similarity on hash bytes
        same = sum(1 for a, b in zip(h, h2) if a == b)
        similarities.append(same / len(h))
    avg_sim = sum(similarities) / len(similarities)
    return 1.0 - avg_sim


def _composite_score(score: CandidateScore, weights: dict[str, float] | None = None) -> float:
    """Compute weighted composite score (0-1). Higher is better."""
    w = weights or {
        "complexity": -0.2,
        "risk": -0.3,
        "test_coverage": 0.2,
        "signal_match": 0.2,
        "novelty": 0.1,
    }
    total = 0.0
    for key, weight in w.items():
        val = getattr(score, key, 0.0)
        total += val * weight
    # Normalise to 0-1
    total = (total + 1.0) / 2.0
    return max(0.0, min(1.0, total))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_candidate(
    candidate: Candidate,
    *,
    signal_vector: dict[str, float] | None = None,
    recent_diffs: list[str] | None = None,
    weights: dict[str, float] | None = None,
) -> CandidateScore:
    """Score a single candidate."""
    score = CandidateScore(candidate_id=candidate.candidate_id)
    score.complexity = _score_complexity(candidate.diff_text)
    score.risk = _score_risk(candidate.diff_text)
    score.test_coverage = _score_test_coverage(candidate.diff_text)
    score.signal_match = _score_signal_match(candidate.diff_text, signal_vector)
    score.novelty = _score_novelty(candidate.diff_text, recent_diffs or [])
    score.composite = _composite_score(score, weights)
    candidate.score = score
    return score


def rank_candidates(
    candidates: list[Candidate],
    *,
    signal_vector: dict[str, float] | None = None,
    recent_diffs: list[str] | None = None,
    weights: dict[str, float] | None = None,
    strategy: str = "composite",
) -> list[Candidate]:
    """Score and rank *candidates* from best to worst.

    *strategy* can be ``"composite"`` (default) or ``"tournament"``.
    """
    for c in candidates:
        evaluate_candidate(
            c, signal_vector=signal_vector, recent_diffs=recent_diffs, weights=weights
        )

    if strategy == "tournament":
        return _tournament_rank(candidates)
    # Default: sort by composite score descending
    return sorted(candidates, key=lambda c: c.score.composite if c.score else 0.0, reverse=True)


def _tournament_rank(candidates: list[Candidate]) -> list[Candidate]:
    """Pair-wise tournament: winner gets +1 point per match."""
    scores: dict[str, float] = {}
    for c in candidates:
        scores[c.candidate_id] = 0.0
    for i, a in enumerate(candidates):
        for b in candidates[i + 1 :]:
            sa = a.score.composite if a.score else 0.0
            sb = b.score.composite if b.score else 0.0
            if sa > sb:
                scores[a.candidate_id] += 1.0
            elif sb > sa:
                scores[b.candidate_id] += 1.0
            else:
                scores[a.candidate_id] += 0.5
                scores[b.candidate_id] += 0.5
    return sorted(candidates, key=lambda c: scores.get(c.candidate_id, 0.0), reverse=True)


def pick_best(
    candidates: list[Candidate],
    *,
    signal_vector: dict[str, float] | None = None,
    recent_diffs: list[str] | None = None,
    weights: dict[str, float] | None = None,
    min_score: float = 0.0,
) -> Candidate | None:
    """Return the top-ranked candidate, or ``None`` if all scores < *min_score*."""
    ranked = rank_candidates(
        candidates, signal_vector=signal_vector, recent_diffs=recent_diffs, weights=weights
    )
    if not ranked:
        return None
    top = ranked[0]
    if top.score and top.score.composite < min_score:
        return None
    return top
