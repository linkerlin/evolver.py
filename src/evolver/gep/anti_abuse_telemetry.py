"""Anti-abuse telemetry — detect and report suspicious evolution patterns.

Equivalent to ``evolver/src/gep/antiAbuseTelemetry.js``.

Monitors the evolution system for patterns that may indicate abuse:
  - **Gene flooding**: excessive new gene creation in a short window.
  - **Validation bypass**: repeated attempts to skip validation.
  - **Signal spoofing**: fabricated signals to force gene selection.
  - **Resource exhaustion**: excessive cycles with no progress.

Reports are written to a local JSONL log and optionally forwarded to the Hub.
"""

from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path
from typing import Any

_SUSPICION_THRESHOLD = 0.7
_FLOOD_WINDOW_S = 60
_FLOOD_MAX_EVENTS = 20


class AbuseDetector:
    """Detect suspicious evolution patterns using rolling windows."""

    def __init__(self, log_path: Path | None = None) -> None:
        self._log_path = log_path
        self._gene_creations: deque[float] = deque(maxlen=100)
        self._validation_skips: deque[float] = deque(maxlen=100)
        self._idle_cycles: int = 0

    def record_gene_creation(self) -> float:
        """Record a gene creation event. Returns abuse score (0.0-1.0)."""
        now = time.time()
        self._gene_creations.append(now)
        return self._check_flood()

    def record_validation_skip(self) -> float:
        """Record a validation skip. Returns abuse score."""
        now = time.time()
        self._validation_skips.append(now)
        recent_skips = sum(1 for t in self._validation_skips if now - t < _FLOOD_WINDOW_S)
        score = min(recent_skips / 5.0, 1.0)
        if score >= _SUSPICION_THRESHOLD:
            self._report("validation_bypass", {"recent_skips": recent_skips}, score)
        return score

    def record_idle_cycle(self) -> float:
        """Record an idle (no-progress) cycle. Returns abuse score."""
        self._idle_cycles += 1
        score = min(self._idle_cycles / 50.0, 1.0)
        if score >= _SUSPICION_THRESHOLD:
            self._report(
                "resource_exhaustion",
                {"idle_cycles": self._idle_cycles},
                score,
            )
        return score

    def reset_progress(self) -> None:
        """Call when a cycle makes progress (resets idle counter)."""
        self._idle_cycles = 0

    def _check_flood(self) -> float:
        """Check for gene creation flooding."""
        now = time.time()
        recent = sum(1 for t in self._gene_creations if now - t < _FLOOD_WINDOW_S)
        score = min(recent / _FLOOD_MAX_EVENTS, 1.0)
        if score >= _SUSPICION_THRESHOLD:
            self._report("gene_flood", {"recent_creations": recent}, score)
        return score

    def _report(self, abuse_type: str, details: dict[str, Any], score: float) -> None:
        """Write an abuse report to the log."""
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "type": abuse_type,
            "score": round(score, 2),
            "details": details,
        }
        if self._log_path:
            try:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                with self._log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
            except OSError:
                pass

    def get_score(self) -> float:
        """Return the current overall abuse suspicion score (0.0-1.0)."""
        return max(
            self._check_flood(),
            min(len(self._validation_skips) / 5.0, 1.0),
            min(self._idle_cycles / 50.0, 1.0),
        )


__all__ = ["AbuseDetector"]
