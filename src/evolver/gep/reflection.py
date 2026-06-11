"""Reflection engine — periodic self-evaluation and personality tuning.

Equivalent to Node's ``evolver/src/gep/reflection.js``.

Periodically (e.g. every 24 h or after N mutations) the agent
reflects on its recent performance and adjusts its *personality*
parameters:

* **rigor** — how strict validation should be.
* **creativity** — willingness to try novel approaches.
* **risk_tolerance** — blast-radius appetite.

Reflection reads the memory graph, scores recent attempts, and
proposes personality deltas. The deltas are applied to
:mod:`personality` if they pass a sanity check.

Design notes
------------
* Deterministic — same history → same deltas.
* Deltas are clamped to [-0.2, +0.2] per reflection to avoid
  wild swings.
* Writes to ``personality.json`` via :mod:`personality`.
* Respects the ``enable_reflection`` feature flag.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from evolver.gep.feature_flags import is_enabled
from evolver.gep.memory_graph import try_read_memory_graph_events
from evolver.gep.personality import load_personality, save_personality

logger = logging.getLogger(__name__)

# Maximum delta per reflection
MAX_DELTA = 0.2

# Window for reflection (seconds)
REFLECTION_WINDOW_SECONDS = 86400  # 24 h

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ReflectionDelta:
    rigor: float = 0.0
    creativity: float = 0.0
    risk_tolerance: float = 0.0
    reason: str = ""

    def is_significant(self, threshold: float = 0.05) -> bool:
        return any(abs(v) >= threshold for v in (self.rigor, self.creativity, self.risk_tolerance))


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score_recent_attempts(
    events: list[dict[str, Any]],
    window_seconds: float = REFLECTION_WINDOW_SECONDS,
    now: float | None = None,
) -> tuple[float, float, float]:
    """Return (success_rate, avg_complexity, avg_novelty) for recent attempts.

    *success_rate* — fraction of attempts with positive outcome.
    *avg_complexity* — normalised blast radius (0-1).
    *avg_novelty* — fraction of attempts that are unique.
    """
    t = now if now is not None else time.time()
    cutoff = t - window_seconds
    recent = [e for e in events if e.get("type") == "attempt" and e.get("timestamp", 0) >= cutoff]

    if not recent:
        return 0.5, 0.5, 0.5  # neutral defaults

    successes = sum(
        1
        for e in recent
        if "success" in str(e.get("outcome", "")).lower()
        or "pass" in str(e.get("outcome", "")).lower()
    )
    success_rate = successes / len(recent)

    complexities = []
    for e in recent:
        files = len(e.get("changed_files", []))
        lines = sum(e.get("file_line_counts", {}).values())
        c = min(1.0, (files / 20.0 + lines / 5000.0) / 2.0)
        complexities.append(c)
    avg_complexity = sum(complexities) / len(complexities) if complexities else 0.5

    # Novelty: unique outcomes / total
    unique_outcomes = len({str(e.get("outcome", "")) for e in recent})
    avg_novelty = unique_outcomes / len(recent)

    return success_rate, avg_complexity, avg_novelty


# ---------------------------------------------------------------------------
# Delta computation
# ---------------------------------------------------------------------------


def compute_delta(
    success_rate: float,
    avg_complexity: float,
    avg_novelty: float,
) -> ReflectionDelta:
    """Compute personality deltas from performance metrics.

    Heuristics
    ----------
    * Low success rate  → increase rigor, decrease risk_tolerance.
    * High success rate → increase creativity, increase risk_tolerance slightly.
    * High complexity   → increase rigor.
    * Low novelty       → increase creativity.
    """
    delta = ReflectionDelta()

    # Success rate influence
    if success_rate < 0.5:
        delta.rigor += 0.1
        delta.risk_tolerance -= 0.15
    elif success_rate > 0.8:
        delta.creativity += 0.1
        delta.risk_tolerance += 0.05

    # Complexity influence
    if avg_complexity > 0.7:
        delta.rigor += 0.1
        delta.risk_tolerance -= 0.1
    elif avg_complexity < 0.2:
        delta.creativity += 0.05

    # Novelty influence
    if avg_novelty < 0.3:
        delta.creativity += 0.15

    # Clamp
    delta.rigor = max(-MAX_DELTA, min(MAX_DELTA, delta.rigor))
    delta.creativity = max(-MAX_DELTA, min(MAX_DELTA, delta.creativity))
    delta.risk_tolerance = max(-MAX_DELTA, min(MAX_DELTA, delta.risk_tolerance))

    delta.reason = (
        f"success_rate={success_rate:.0%} complexity={avg_complexity:.0%} novelty={avg_novelty:.0%}"
    )
    return delta


def apply_delta(delta: ReflectionDelta) -> dict[str, float]:
    """Load personality, apply *delta*, clamp to [0, 1], and save.

    Returns the new personality dict.
    """
    personality = load_personality()
    personality["rigor"] = max(0.0, min(1.0, personality.get("rigor", 0.5) + delta.rigor))
    personality["creativity"] = max(
        0.0, min(1.0, personality.get("creativity", 0.5) + delta.creativity)
    )
    personality["risk_tolerance"] = max(
        0.0, min(1.0, personality.get("risk_tolerance", 0.5) + delta.risk_tolerance)
    )
    save_personality(personality)
    logger.info(
        "[Reflection] Applied delta rigor=%+.2f creativity=%+.2f risk=%+.2f (%s)",
        delta.rigor,
        delta.creativity,
        delta.risk_tolerance,
        delta.reason,
    )
    return personality


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def reflect(
    *,
    events: list[dict[str, Any]] | None = None,
    window_seconds: float = REFLECTION_WINDOW_SECONDS,
    now: float | None = None,
    dry_run: bool = False,
) -> ReflectionDelta:
    """Run a full reflection cycle.

    If *dry_run* is ``True``, computes the delta but does **not**
    modify personality.

    Returns the computed :class:`ReflectionDelta`.
    """
    if not is_enabled("enable_reflection"):
        return ReflectionDelta(reason="reflection_disabled")

    if events is None:
        events = try_read_memory_graph_events()

    success_rate, avg_complexity, avg_novelty = _score_recent_attempts(
        events, window_seconds=window_seconds, now=now
    )
    delta = compute_delta(success_rate, avg_complexity, avg_novelty)

    if not dry_run and delta.is_significant():
        apply_delta(delta)
    elif dry_run:
        logger.info("[Reflection] Dry-run delta: %s", delta)

    return delta


def should_reflect(
    *,
    min_attempts: int = 5,
    min_elapsed_seconds: float = 3600,
    last_reflection_timestamp: float | None = None,
    now: float | None = None,
) -> bool:
    """Return ``True`` if enough time / attempts have passed to warrant reflection."""
    t = now if now is not None else time.time()
    if last_reflection_timestamp is None:
        return True
    elapsed = t - last_reflection_timestamp
    return elapsed >= min_elapsed_seconds
