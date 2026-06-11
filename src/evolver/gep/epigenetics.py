"""Epigenetics engine — context-aware gene suppression / activation.

Equivalent to Node's ``evolver/src/gep/epigenetics.js``.

Genes carry *epigenetic marks*: context-dependent annotations that
boost or suppress the gene's expression based on the current
environment fingerprint.

Key concepts
------------
* **Environment fingerprint** — SHA-256 hash of curated env vars.
* **Mark** — ``{"context": <hash>, "boost": float, "created_at": timestamp}``.
* **Suppression** — when the strongest negative mark for the current
  context has ``boost <= HARD_BOOST_THRESHOLD``.
* **Activation** — when the strongest positive mark dominates.
* **Aging** — marks decay over time (half-life default 30 days).

Design notes
------------
* Operates on plain gene dicts so it integrates with any gene store.
* All timestamps are ``time.time()`` (POSIX seconds).
* Deterministic and testable — no external I/O.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# Hard threshold: any mark with boost <= this value suppresses the gene
GENE_EPIGENETIC_HARD_BOOST = -3.0

# Default half-life for mark aging (seconds)
DEFAULT_MARK_HALF_LIFE_DAYS = 30

# ---------------------------------------------------------------------------
# Environment fingerprint
# ---------------------------------------------------------------------------


def capture_env_fingerprint() -> dict[str, str]:
    """Return a curated subset of environment variables."""
    keys = [
        "EVOLVER_MODE",
        "EVOLVER_AGENT_ID",
        "EVOLVER_TASK_TYPE",
        "HOME",
        "USER",
        "PYTHONPATH",
        "PATH",
    ]
    return {k: os.environ.get(k, "") for k in keys}


def env_fingerprint_key(env: dict[str, str]) -> str:
    """Return a stable SHA-256 hash of the env dict."""
    canonical = json.dumps(env, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Mark manipulation
# ---------------------------------------------------------------------------


def apply_mark(
    gene: dict[str, Any],
    context: str,
    boost: float,
    created_at: float | None = None,
) -> None:
    """Add or update an epigenetic mark on *gene*.

    If a mark for the same *context* already exists, it is replaced.
    """
    marks: list[dict[str, Any]] = gene.setdefault("epigenetic_marks", [])
    now = created_at if created_at is not None else time.time()
    for mark in marks:
        if mark.get("context") == context:
            mark["boost"] = boost
            mark["created_at"] = now
            return
    marks.append({"context": context, "boost": boost, "created_at": now})


def remove_mark(gene: dict[str, Any], context: str) -> bool:
    """Remove the mark matching *context*. Return ``True`` if removed."""
    marks: list[dict[str, Any]] = gene.get("epigenetic_marks") or []
    original_len = len(marks)
    gene["epigenetic_marks"] = [m for m in marks if m.get("context") != context]
    return len(gene["epigenetic_marks"]) < original_len


def boost_gene(
    gene: dict[str, Any],
    context: str | None = None,
    amount: float = 1.0,
) -> None:
    """Boost *gene* expression in *context* (or current env if omitted)."""
    ctx = context or env_fingerprint_key(capture_env_fingerprint())
    apply_mark(gene, ctx, amount)


def suppress_gene(
    gene: dict[str, Any],
    context: str | None = None,
) -> None:
    """Suppress *gene* expression in *context* (or current env if omitted)."""
    ctx = context or env_fingerprint_key(capture_env_fingerprint())
    apply_mark(gene, ctx, GENE_EPIGENETIC_HARD_BOOST)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def get_marks(gene: dict[str, Any]) -> list[dict[str, Any]]:
    """Return all epigenetic marks on *gene*."""
    return list(gene.get("epigenetic_marks") or [])


def get_boost_for_context(gene: dict[str, Any], context: str) -> float:
    """Return the boost value for *context*, or ``0.0`` if no mark."""
    for mark in get_marks(gene):
        if mark.get("context") == context:
            return float(mark.get("boost", 0.0))
    return 0.0


def is_suppressed(
    gene: dict[str, Any],
    env: dict[str, str] | None = None,
) -> bool:
    """Return ``True`` if *gene* is epigenetically suppressed in *env*."""
    key = env_fingerprint_key(env or capture_env_fingerprint())
    boost = get_boost_for_context(gene, key)
    return boost <= GENE_EPIGENETIC_HARD_BOOST


def is_active(
    gene: dict[str, Any],
    env: dict[str, str] | None = None,
) -> bool:
    """Return ``True`` if *gene* is not suppressed in *env*."""
    return not is_suppressed(gene, env)


def get_active_genes(
    genes: list[dict[str, Any]],
    env: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Filter *genes* to those not suppressed in *env*."""
    return [g for g in genes if is_active(g, env)]


# ---------------------------------------------------------------------------
# Aging
# ---------------------------------------------------------------------------


def age_marks(
    gene: dict[str, Any],
    half_life_days: float = DEFAULT_MARK_HALF_LIFE_DAYS,
    now: float | None = None,
) -> None:
    """Decay all marks on *gene* based on elapsed time.

    Boost decays exponentially: ``new_boost = old_boost * 0.5^(elapsed / half_life)``.
    Marks whose absolute boost drops below ``0.1`` are removed.
    """
    marks: list[dict[str, Any]] = gene.get("epigenetic_marks") or []
    if not marks:
        return
    t = now if now is not None else time.time()
    half_life = half_life_days * 86400.0
    if half_life <= 0:
        return
    kept: list[dict[str, Any]] = []
    for mark in marks:
        elapsed = t - mark.get("created_at", t)
        old_boost = float(mark.get("boost", 0.0))
        new_boost = old_boost * (0.5 ** (elapsed / half_life))
        if abs(new_boost) >= 0.1:
            mark["boost"] = new_boost
            kept.append(mark)
    gene["epigenetic_marks"] = kept


def age_all_genes(
    genes: list[dict[str, Any]],
    half_life_days: float = DEFAULT_MARK_HALF_LIFE_DAYS,
) -> None:
    """Run :func:`age_marks` on every gene in *genes*."""
    for gene in genes:
        age_marks(gene, half_life_days)
