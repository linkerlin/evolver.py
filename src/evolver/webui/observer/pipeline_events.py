"""Pipeline event timeline + statistical analysis for WebUI."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .jsonl import stream_jsonl

_PIPELINE_TYPES = frozenset(
    {"pipeline_start", "pipeline_phase", "pipeline_end", "cycle_start", "cycle_end"}
)


def pipeline_timeline(*, limit: int = 100, memory_dir: Path | None = None) -> list[dict[str, Any]]:
    """Return recent pipeline-phase events for timeline visualization."""
    from evolver.gep.paths import get_memory_dir

    mem = memory_dir or get_memory_dir()
    events = list(stream_jsonl(mem / "events.jsonl", limit=limit * 3))
    pipeline = [e for e in events if e.get("type") in _PIPELINE_TYPES]
    return pipeline[-limit:]


def pipeline_stats(*, memory_dir: Path | None = None) -> dict[str, Any]:
    """Aggregate pipeline statistics: stage durations, bottlenecks, cycle cadence."""
    from evolver.gep.paths import get_memory_dir

    mem = memory_dir or get_memory_dir()
    events = list(stream_jsonl(mem / "events.jsonl"))

    # Collect per-cycle phase durations
    cycle_durations: list[float] = []
    phase_total_time: dict[str, float] = defaultdict(float)
    phase_counts: dict[str, int] = defaultdict(int)
    phase_max_time: dict[str, float] = defaultdict(float)
    phase_min_time: dict[str, float] = defaultdict(float)
    slowest_phase: str | None = None
    slowest_phase_avg: float = 0.0

    cycle_count = 0
    success_count = 0
    failure_count = 0

    for e in events:
        t = e.get("type", "")
        if t == "cycle_end":
            cycle_count += 1
            outcome = e.get("outcome", "?")
            if outcome == "success":
                success_count += 1
            elif outcome == "failed":
                failure_count += 1
            dur = e.get("duration_ms")
            if isinstance(dur, (int, float)) and dur > 0:
                cycle_durations.append(float(dur) / 1000)
        elif t == "pipeline_phase":
            phase = e.get("phase", "?")
            dur = e.get("duration_ms")
            if isinstance(dur, (int, float)) and dur > 0:
                d = float(dur)
                phase_total_time[str(phase)] += d
                phase_counts[str(phase)] += 1
                prev = phase_max_time.get(str(phase), 0)
                if d > prev:
                    phase_max_time[str(phase)] = d
                prev_min = phase_min_time.get(str(phase), float("inf"))
                if d < prev_min:
                    phase_min_time[str(phase)] = d

    # Compute per-phase averages and find bottleneck
    phase_averages: dict[str, float] = {}
    for phase, total in phase_total_time.items():
        count = phase_counts[phase]
        avg = total / count if count else 0
        phase_averages[phase] = avg
        if avg > slowest_phase_avg:
            slowest_phase_avg = avg
            slowest_phase = phase

    # Cycle stats
    cycle_avg = sum(cycle_durations) / len(cycle_durations) if cycle_durations else 0
    cycle_max = max(cycle_durations) if cycle_durations else 0
    cycle_min = min(cycle_durations) if cycle_durations else 0

    return {
        "cycles": {
            "total": cycle_count,
            "success": success_count,
            "failure": failure_count,
            "avg_duration_sec": round(cycle_avg, 1),
            "max_duration_sec": round(cycle_max, 1),
            "min_duration_sec": round(cycle_min, 1),
        },
        "phases": {
            name: {
                "count": phase_counts[name],
                "avg_ms": round(phase_averages[name], 1),
                "max_ms": round(phase_max_time[name], 1),
                "min_ms": round(phase_min_time[name], 1),
            }
            for name in sorted(phase_counts)
        },
        "bottleneck": {
            "phase": slowest_phase,
            "avg_ms": round(slowest_phase_avg, 1),
        },
    }
