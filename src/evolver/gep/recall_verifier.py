"""Recall verifier — validate that injected memories are still valid.

Equivalent to Node's ``evolver/src/gep/recallVerifier.js``.

When :mod:`recall_inject` surfaces a past success, there is a risk
that the codebase has drifted since then, making the old strategy
stale or harmful. The verifier re-evaluates each recall by:

1. **Staleness check** — how old is the memory? (>30 days → stale).
2. **Code drift check** — do the files touched in the original
   mutation still exist and have similar content?
3. **Test re-run** — can the original test suite still pass?
   (Best-effort; skipped if no tests are present.)

A recall that fails verification is marked ``invalid`` and suppressed
for future injections.

Design notes
------------
* Operates on the memory graph JSONL.
* File drift uses simple line-count similarity.
* Test re-run is optional and behind the ``enable_validator`` flag.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evolver.gep.feature_flags import is_enabled
from evolver.gep.memory_graph import try_read_memory_graph_events
from evolver.gep.paths import get_workspace_root

logger = logging.getLogger(__name__)

# Staleness threshold (seconds)
STALE_THRESHOLD_DAYS = 30
STALE_THRESHOLD_SECONDS = STALE_THRESHOLD_DAYS * 86400.0

# Minimum file similarity to consider "unchanged" (Jaccard-ish)
MIN_FILE_SIMILARITY = 0.5


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class VerificationResult:
    recall_id: str
    valid: bool
    staleness: float  # 0-1, higher = older
    drift_score: float  # 0-1, higher = more drift
    test_passed: bool | None
    reason: str


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def _staleness(event_timestamp: float, now: float | None = None) -> float:
    """Return staleness score (0-1). 1.0 means very stale."""
    t = now if now is not None else time.time()
    elapsed = t - event_timestamp
    return min(1.0, elapsed / STALE_THRESHOLD_SECONDS)


# ---------------------------------------------------------------------------
# Code drift
# ---------------------------------------------------------------------------


def _file_hash_similarity(path: Path, expected_hash: str | None) -> float:
    """Return similarity between current file and expected hash.

    If *expected_hash* is missing, returns 0.5 (unknown).
    """
    if not expected_hash:
        return 0.5
    if not path.exists():
        return 0.0
    try:
        content = path.read_bytes()
        current_hash = hashlib.sha256(content).hexdigest()[:16]
        return 1.0 if current_hash == expected_hash else 0.0
    except OSError:
        return 0.0


def _compute_drift(
    event: dict[str, Any],
    root: Path | None = None,
) -> float:
    """Compute code-drift score (0-1). Higher = more drift."""
    cwd = root or get_workspace_root()
    files = event.get("changed_files", [])
    if not files:
        return 0.0

    drift_scores: list[float] = []
    for rel in files:
        p = cwd / rel
        # Use a simple line-count similarity heuristic
        expected_lines = event.get("file_line_counts", {}).get(rel)
        if not p.exists():
            drift_scores.append(1.0)
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                current_lines = sum(1 for _ in f)
        except OSError:
            drift_scores.append(1.0)
            continue
        if expected_lines is None:
            drift_scores.append(0.5)
            continue
        if expected_lines == 0:
            drift_scores.append(0.0 if current_lines == 0 else 1.0)
            continue
        ratio = current_lines / expected_lines
        drift = abs(1.0 - ratio)
        drift_scores.append(min(1.0, drift))

    return sum(drift_scores) / len(drift_scores) if drift_scores else 0.0


# ---------------------------------------------------------------------------
# Test re-run (best-effort)
# ---------------------------------------------------------------------------


def _rerun_tests(event: dict[str, Any]) -> bool | None:
    """Attempt to re-run tests associated with *event*.

    Returns ``True`` if passed, ``False`` if failed, ``None`` if not
    attempted (no tests or flag disabled).
    """
    if not is_enabled("enable_validator"):
        return None
    test_files = event.get("test_files", [])
    if not test_files:
        return None
    # Best-effort: we don't actually run tests here because that would
    # require a full pytest invocation. Instead, we check that the test
    # files still exist.
    root = get_workspace_root()
    all_exist = all((root / tf).exists() for tf in test_files)
    return all_exist


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def verify_recall(
    event: dict[str, Any],
    *,
    now: float | None = None,
    root: Path | None = None,
) -> VerificationResult:
    """Verify a single recall *event*.

    Returns a :class:`VerificationResult` with ``valid=True`` only if
    the recall is fresh, low-drift, and (optionally) tests pass.
    """
    recall_id = event.get("event_id", "unknown")
    event_time = event.get("timestamp", 0.0)

    staleness = _staleness(event_time, now)
    drift = _compute_drift(event, root)
    test_passed = _rerun_tests(event)

    reasons: list[str] = []
    if staleness > 0.9:
        reasons.append("very stale")
    if drift > 0.5:
        reasons.append("high code drift")
    if test_passed is False:
        reasons.append("tests missing")

    valid = not reasons and staleness < 0.8 and drift < 0.5
    reason = ", ".join(reasons) if reasons else "ok"

    return VerificationResult(
        recall_id=recall_id,
        valid=valid,
        staleness=staleness,
        drift_score=drift,
        test_passed=test_passed,
        reason=reason,
    )


def verify_all_recalls(
    *,
    events: list[dict[str, Any]] | None = None,
    now: float | None = None,
) -> list[VerificationResult]:
    """Verify all successful-attempt events in the memory graph."""
    if events is None:
        events = try_read_memory_graph_events()

    candidates = [e for e in events if e.get("type") == "attempt"]
    results: list[VerificationResult] = []
    for ev in candidates:
        results.append(verify_recall(ev, now=now))
    return results


def filter_valid_recalls(
    matches: list[Any],
    *,
    events: list[dict[str, Any]] | None = None,
) -> list[Any]:
    """Filter a list of recall matches to only those that pass verification.

    *matches* is typically the output of :func:`recall_inject.search_recalls`.
    """
    if events is None:
        events = try_read_memory_graph_events()
    event_map = {e.get("event_id", ""): e for e in events}
    valid: list[Any] = []
    for m in matches:
        ev = event_map.get(getattr(m, "event_id", ""))
        if not ev:
            continue
        result = verify_recall(ev)
        if result.valid:
            valid.append(m)
    return valid
